Status: plan (revision 3, 2026-11-25, Dennis rounds 1-2 folded; slice plan for S1b and S1c; anchored to PR #806 head `1a13d250b`, branch `feat/trs-s1a`)

# TEXT-REDACT-RUST-SPLICE slices S1b and S1c: the text_redact Arrow splice helper, then its routes

Owner: Cam. Author: Opus (plan author). Roadmap row: TEXT-REDACT-RUST-SPLICE (group mask, 1.0.x). Scope: decoy-engine. The CLI gets it with its next engine pin. Risk: R2 for both slices. A missed span can expose a data value, and the release contract freezes masked bytes.

Parent plan: `docs/plans/2026-11-22-text-redact-rust-splice.md` revision 9.1 on branch `plan/text-redact-rust-splice` (Codex round 5 GO). This file does not repeat the parent. It turns parent sections 4.2, 4.3, 5.3, 5.4, 8, 9 and 11 into build steps for S1b and S1c, re-anchors every line number to the S1a head and records what changed since the parent was written. Where this file and the parent disagree, this file wins for S1b and S1c.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `security.md`, `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md`, `CONTRIBUTING.md` and `CODEMAP.md`.

Anchors: paths starting with `execution/` or `reasons/` are under `src/decoy_engine/`. All Python line numbers are read at `1a13d250b` (#806). That head equals engine main `2b8a47fbe` for every Python file named here except `execution/native/_text_redact_kernel.py`, which S1a extends.

## Changes in revision 2 (Dennis round 1)

- HIGH: today sequential and out-of-core already report `rust_companion` for an admitted text_redact column that ran nothing in Rust. S1c moves those idle columns to `arrow_python` and writes the label in the two `entry()` methods (sections 5.5, 7, 10).
- MEDIUM: splice translation uses an F29-visible table lookup (5.3); one extracted label helper (5.1, M2); a CI conversion guard for M7 (AT-9b); combined `_crypto_ext.py` budget with FPE S2b (7).
- LOW: unresolvable explicit detector lists, `__all__` line, reason release checks, `MemoryError` passthrough, reason block comment.

## Changes in revision 3 (Dennis round 2)

- MEDIUM: the label call applies to admitted columns only; declined columns keep `python_scalar` (5.5 item 8).
- MEDIUM: S1c names the shared fixtures and assertions it changes, and its gate adds a full suite (5.5 item 9, section 6).
- MEDIUM: AT-9b keeps the runtime `pa.array` patch and replaces the `to_pylist` patch, which pyarrow's immutable types refuse, with a static guard.
- LOW: the splice subscript is passed inline to `ExecutionError`.

## 1. Frame

State of the row on 2026-11-25:

| Slice | State |
|---|---|
| S0 detector offset guard | merged |
| S1a Rust outcomes, Arrow entry `text_span_splice`, bound probe | PR #806, open, head `1a13d250b` |
| S1t chunk-capable transport and out-of-core FK staging | not built, no branch or PR |
| S1b text_redact helper (this file) | planned here |
| S1c text_redact routes and labels (this file) | planned here |
| S2a, S2b | parent plan, unchanged |

What S1a gives S1b, read at `1a13d250b`:

- `execution/native/_text_redact_kernel.py` (436 lines): `CATALOG_VERSION = 2` (:69), `SPLICE_CONTRACT_VERSION = 1` (:115), `_EXPECTED_ABI` (:118), `_KAT_CELLS` (:121), `CompanionCompat` (:140), `_decide` (:233), `companion_compat()` (:266), `load_text_redact_kernel` (:290), `load_text_span_splice` (:304), `requested_rust_ids` (:331), `merge_text_redact_spans` (:354).
- `load_text_span_splice()` returns a callable `call(values, *, detector_ids, outs, gap_out, native_threads=None) -> list[tuple[Array, Array]]`, or `None` for E1 and E1b. It fixes `catalog_version` and `splice_contract_version` itself.
- `requested_rust_ids(None)` still returns `list(SUPPORTED_IDS)` in catalog order (:340). Parent M9 is still open and is S1b's.

Run-card labels today (Dennis round 1): the sequential `ColumnDecision.entry()` (`execution/_sequential_native_decisions.py:62-73`) writes `executed_backend: self.backend` when `rows > 0`, and the out-of-core `TextRedactColumnDecision.entry()` (`out_of_core/_text_redact_native.py:112-118`) writes it when `native_calls > 0`. For an admitted text_redact column `self.backend` is `rust_companion`, so both routes report `rust_companion` today even though the list-based helper ran nothing in Rust. `tests/parity/test_ooc_text_redact_native_routing.py:179` asserts that for an all-null column.

Today's helper, `native_text_redact` at `execution/native/_kernels_scalar.py:149` (file 384 lines), converts the column with `to_pylist`, stringifies non-null values, calls `text_redact_candidates` in batches of `_TEXT_REDACT_KERNEL_BATCH = 65_536` (:146), merges in Python, splices each cell with `_splice` and rebuilds with `pa.array(..., pa.string())`. Four route sites call it:

| Route | Call site |
|---|---|
| Unified and chunked (shared step) | `execution/native/_operator_step.py:343` (file 569 lines) |
| Sequential | `execution/_sequential_native_ops.py:474`, import at :52 (file 593 lines, must stay at or below 600) |
| Out-of-core | `execution/out_of_core/_text_redact_native.py:224` inside `native_text_redact_array` (:208), called from `out_of_core/_mask.py:175` |

The text_redact operator spec is `execution/_operator_registry.py:162-172`: `operator_id="native_text_redact"`, `planned_backend=ARROW_PYTHON`, `required_kernel=None`, `positive_kernel_evidence=False`, `full_frame_assembly="null_on_empty"`. The sequential recorder is `execution/_sequential_native.py:470` (file pinned at 700 lines).

### Change since the parent was written

- S1t is not built. The parent orders S1t before S1b. S1b adds a helper that no route calls, so it needs nothing from S1t. This plan lets S1b merge before S1t (OWNER CALL, section 12). S1c still needs S1t merged, because S1c sends the helper's possibly chunked output through route consumers that only S1t widens.
- The unused-adapter guard in `tests/sentry/test_reason_registry.py` is at :298.
- The parent put the validator and scatter in `_text_redact_kernel.py`. S1a grew that file to 436 lines, so S1b puts them in `_text_mask_native_splice.py` (188 lines) instead. Both strategies already import that module for splice work (section 7).

## 2. Established solutions

The parent section 2 covers the Rust side. For the Python side the established tools are Arrow compute and the existing engine helpers. `pyarrow.compute` has `if_else`, `replace_with_mask` and `filter`, which scatter repaired rows without a Python list over eligible rows. The engine already cuts wide string intermediates with `split_narrow_text`. No new dependency.

### Reuse inventory

- `load_text_span_splice` and `companion_compat` (`_text_redact_kernel.py:304`, `:266`): the only way S1b reaches the additive entry. S1b adds no second probe.
- `load_text_redact_kernel` (`_text_redact_kernel.py:290`) and `merge_text_redact_spans` (:354): the E1b path for wheels without the additive entry.
- `iter_spans` and `_splice` (`execution/_strategies/_text_redact.py:198`, label format at :216): the repair path for declined cells and the full E1 path.
- The token UTF-8 check in `_text_mask_native_splice.py:96-103` (`token.encode("utf-8")`, `UnicodeEncodeError` gives `None`): S1b calls the same check for the token, so text_redact and text_mask refuse the same literals.
- `split_narrow_text` and `_OFFSET_LIMIT = 2**31 - 1` (`src/decoy_engine/_arrow_types.py:67`, `:42`): cut wide scatter intermediates.
- `_translate_compiled_kernel_error` (`execution/native/_crypto_ext.py:362`): the one coded-error parser. S1b extends it in place.
- `executed_backend(planned_backend, *, native_admitted, kernel_idle)` (`execution/native/_chunked_evidence.py:120`): S1c's only backend selector.
- `scripts/bench_text_redact.py`: S1b extends its workers. No new benchmark script.

## 3. Guarantee and non-goals

After S1b:

1. `splice_text_redact(array, *, detectors, token, label_token) -> (values, ran)` returns the same bytes, nulls and row order as the oracle for every input the current helper accepts, on every companion state (E1, E1b, current wheel).
2. No production route calls it. Every job runs today's path under today's label. The only callers are tests and the benchmark.
3. A boundary failure after a successful probe raises one of the five registered `text_splice_*` errors with fixed text and no cause or context.

After S1c:

4. Every text_redact route calls the helper. A batch that splices a real cell in Rust reports `rust_companion`. An admitted column whose every batch was idle reports `arrow_python`. The old list-based body is gone.
5. Masked bytes do not change on any route (AT-1, AT-10).

Non-goals: text_mask (S2a); skew CI tests and the final-head mutation replay (S2b); a new Rust capability; an ABI bump; NER; any change to admission, FK routing or reason codes other than the five new runtime reasons.

## 4. Enumerations

### 4.1 Exit paths of `splice_text_redact`

Parent section 4.2 holds the full list. The S1b mapping:

1. E1: `load_text_span_splice()` and `load_text_redact_kernel()` both return `None`. Full Python detection and `_splice` per non-null cell. `ran=False`.
2. E1b: additive entry `None`, candidates loader bound. Apply the Python offset guard (section 5.2) before calling candidates, then the old candidates-plus-merge path on fitting rows and full Python on guarded rows. `ran=False`.
3. E2 (private zero detectors): `detectors == ()`, or an explicit list that resolves to no supported id (for example `["foo"]`), returns stringified values with nulls and `ran=False`, with no kernel call. `detectors is None` means all built-ins.
4. E3: a null input row is null in the output, with no decline and no splice credit.
5. E4: a non-null row the Rust predicate declines (mask bit true) is repaired in Python with `iter_spans` plus `_splice`. A token that fails the UTF-8 check takes the E1 path for the whole call, matching today's behavior, including success for a no-match cell.
6. E5: an eligible non-null row takes the Rust output. `ran=True` if any such row exists.
7. E6: the additive call raises after a successful probe. Translate through `_translate_compiled_kernel_error` with the splice family. No retry on another path.
8. E7: a malformed return (pair shape, lengths, types, mask nulls, a true bit on a null row, wrong output validity, missing pieces) raises `text_splice_output_invalid` before repair. A wrong null position after scatter raises the same code.

### 4.2 Routes

- S1b: no route changes. AT-5 is not run in S1b because no route calls the helper.
- S1c: unified and chunked through `_operator_step.py:343`; sequential through `_sequential_native_ops.py:474` and the recorder at `_sequential_native.py:470`; out-of-core through `out_of_core/_text_redact_native.py:224`. The full-frame oracle (`TextRedactHandler.run`) does not change and stays the reference.

### 4.3 FK shapes

N/A: S1b and S1c change how an admitted text column is executed. FK admission, key handling and the out-of-core FK staging (S1t) do not change in these slices. AT-10 runs the existing sequential payload-next-to-key regression to show it.

### 4.4 Fields

- `detectors`: `None` means all built-ins, expanded in `_SPAN_DETECTORS` insertion order (`detection/detectors.py:841`) and filtered to `SUPPORTED_IDS` (M9 fix). Explicit lists keep first-seen order. Unknown names are dropped as the oracle drops them.
- `token`: sent as the Replace literal only when `label_token` is false. A token that fails the shared UTF-8 check selects E1.
- `label_token`: when true, each detector's literal is `redaction_label(id)` (section 5.1), and the token is not encoded, checked or sent.
- `ner`: unchanged config rejection in `execution/native/_operator_config_rejections.py`.

### 4.5 Output surfaces

- Masked values, nulls, row order and Arrow type (`string` for a fitting result, `ChunkedArray` of `string` when the result passes the offset ceiling).
- The `ran` flag (S1b), and from S1c the run card `planned_backend` and `executed_backend`, `native_calls` and the chunked branch activation count.
- Public errors: the five `runtime/text_splice_*` codes with fixed summaries.
- Docs: `docs/execution-backends.md:22,74` and the text_redact evidence paragraph of `docs/compatibility-contract.md` (:1049 onward). S1c updates both.

### 4.6 Codes

Five runtime reasons, declared in S1b in the ExecutionError block of `reasons/runtime/_part3.py` (the block that starts at :449), under their own section comment, since the block's existing comment covers post-scan codes. Each has a fixed summary and `since=UNRELEASED` (`CONTRIBUTING.md:57`):

- `runtime/text_splice_unsupported_type`
- `runtime/text_splice_catalog_mismatch`
- `runtime/text_splice_contract_mismatch`
- `runtime/text_splice_unknown_detector`
- `runtime/text_splice_output_invalid` (also the code for an unknown boundary failure and for every E7 case)

`_part3.py` is 553 lines. Five declarations add about 30 lines. If the S1b merge base has already moved the file past 570 lines, declare the five in a new `reasons/runtime/_text_splice.py` and add its star export to `reasons/runtime/__init__.py`. That module is outside the frozen native package fan-out.

## 5. Design

### 5.1 The helper (S1b)

Add `splice_text_redact` to `execution/native/_kernels_scalar.py` below `native_text_redact` and export it in `__all__` (:378). Today the label is an inline f-string in `_splice` (`_strategies/_text_redact.py:216`). S1b extracts it as `redaction_label(detector_id) -> str` in the same module; `_splice` and the helper both call it, so there is one copy. Steps, in order:

1. Resolve the detector list. `ids = requested_rust_ids(detectors)` after the M9 fix. An empty `ids` (from `()` or from a list of unknown names) returns E2 without a kernel call.
2. Resolve literals. Label mode: one `redaction_label(id)` per id. Literal mode: run the shared UTF-8 check on the token. A failure selects E1.
3. Bind. `entry = load_text_span_splice()`. If `None`, take E1b or E1 (section 5.2 guard first). Keep non-string wrapper inputs (integer, float, Boolean) on the old null-aware stringification path and send them to the E1b or E1 logic, as today.
4. Walk. For each chunk of a `ChunkedArray` (or the single Array), cut zero-copy slices of at most `_TEXT_REDACT_KERNEL_BATCH` rows. Call `entry(slice, detector_ids=ids, outs=outs, gap_out=None)` once per slice. A zero-row input returns `pa.array([], pa.string())` and `ran=False` with no call.
5. Validate. Pass every returned sequence through `_checked_splice_output(source_slice, pieces)`: a non-empty list of pairs; each pair a `string` or `large_string` Array and a `bool` Array of equal length; piece lengths sum to the slice length; the mask has zero nulls; no true bit on a null source row; output null exactly where the source is null or the mask is true. Any failure raises `text_splice_output_invalid`.
6. Repair and scatter. Collect the true mask positions. For each, run `iter_spans` plus `_splice` on the source cell (once per declined cell). Write the repaired strings back with Arrow compute over the piece, using `large_string` for the intermediate when repaired rows grow the payload, then `split_narrow_text` before narrowing to `string`. Check that final null positions equal source null positions.
7. Assemble. Return a single `string` Array when all pieces fit `_OFFSET_LIMIT`. Otherwise return a `ChunkedArray` of `string` in input order. Never concatenate past the limit. `ran` is true when any piece has a non-null row with a false mask bit.

The helper never calls `to_pylist` on eligible input or output (AT-9 guard). Repair touches only declined cells.

### 5.2 Python offset guard (S1b)

S0 made both legacy Rust detectors decline a cell past the detector offset limit. Older wheels still narrow offsets to u32. On the E1b path, before calling `text_redact_candidates`, set aside every non-null row whose UTF-8 byte length exceeds `_DETECTOR_OFFSET_LIMIT = 2**32 - 1` and run those rows through full Python. The guard is one function, `partition_detector_rows(texts, *, limit=_DETECTOR_OFFSET_LIMIT)`, in `_text_mask_native_splice.py`, so S2a reuses it for `text_mask_detect_splice`. AT-3 detector offsets injects a 64-byte limit through the keyword and runs on a pre-S0 wheel.

### 5.3 Error translation (S1b)

Extend `_translate_compiled_kernel_error` in `_crypto_ext.py:362` with a keyword `family` that takes `"crypto"` (default, current behavior), `"fpe"` or `"splice"`. Keep its single `str(exc).partition(": ")` at :369.

- `crypto`: unchanged. `seed_wrong_length` and `namespace_empty` give `DeterminismError`, `mixed_object_not_native` gives `GenerationError(NATIVE_TYPE_NOT_ADMITTED)`, anything else returns `exc`.
- `fpe`: the two determinism codes only. Anything else returns `exc` unchanged. This is today's `_translate_compiled_fpe_error` behavior.
- `splice`: a module-level dict `_SPLICE_REASONS` maps each of the five Rust code strings to its registry symbol (all values are registry symbols). The translator checks `code in _SPLICE_REASONS`, then passes `_SPLICE_REASONS[code]` inline as the `ExecutionError` argument (not through a local name, which the scanner classes as dynamic at `_reason_scan.py:262-270`), with that symbol and its fixed summary. No `.get(code, default)`: the F29 scanner (`tests/sentry/_reason_scan.py:247-290`) counts only a direct symbol or a subscript of an all-symbol module dict as registry-backed, and a `.get` call adds an inventory row. Any other code, and any exception other than `ValueError` and `MemoryError`, maps to `text_splice_output_invalid`. `MemoryError` propagates unchanged so an out-of-memory failure is not reported as bad output. The detail after `": "` is never read.

`_translate_compiled_fpe_error` in `execution/native/_fpe_ext.py:50` becomes a one-line delegate, `return _translate_compiled_kernel_error(exc, family="fpe")`. Its caller at `_fpe_ext.py:157` does not change. The helper raises the translated error outside the `except` block so `__cause__` and `__context__` are both `None`.

Ratchet edits in the same commit, each a decrease:

| File | Change |
|---|---|
| `tests/sentry/baselines/engine-exception-text-copies.json` | remove key `audit::execution/native/_fpe_ext.py::_translate_compiled_fpe_error::str(exc)::assign`; total copies 107 to 106 |
| `tests/sentry/safe_output/test_exception_text_copy.py:39` | `AUDIT_PARITY` 100 to 99 |
| `tests/fixtures/f29/producer-inventory.json` and `tests/sentry/baselines/f29-producer-inventory.json` | remove site `execution/native/_fpe_ext.py::_translate_compiled_fpe_error::kw::code`; 1,382 to 1,381 rows, 1,212 to 1,211 keys |
| `tests/sentry/test_reason_registry.py:185` | remove the `("execution/native/_fpe_ext.py", "_translate_compiled_fpe_error")` entry from `ADAPTERS`; 102 to 101 |

The crypto census key stays. New splice factories pass registry symbols, so the live F29 scan must show exactly 1,381 sites at the S1b head. A new row means a factory passes a string code, which is a defect to fix in the code, not a fixture update. Run the unused-adapter guard (`test_reason_registry.py:298`), the live census, baseline registry equality and `scripts/dev/ratchet_check.py` against the merge base.

### 5.4 Resolver order (S1b, M9)

`requested_rust_ids(None)` returns `[d for d in _SPAN_DETECTORS if d in _SUPPORTED_SET]` in insertion order. Explicit lists are unchanged. Candidate indices from Rust keep catalog order (`CATALOG_VERSION` contract), so `merge_text_redact_spans` is unaffected. Update `tests/native/test_c6c_ii_text_redact_rust.py:648`, which asserts the old catalog order, in the same commit.

### 5.5 Route switch and evidence (S1c)

1. Point all four call sites at `splice_text_redact`. Each unpacks `(values, ran)`.
2. Delete the old `native_text_redact` body and its name from `__all__`. Search every direct caller in `src/` and `tests/` and move them to the new helper.
3. Carry `ran` on `StepResult` and `NativeResult` as an optional field (default `None` for other strategies).
4. Shared step: OR `ran` across batches. Record the `when:` branch activation separately from `ran`. The zero-selection return at `_operator_step.py:542` does no strategy work and records no activation.
5. Sequential: replace the recorder at `_sequential_native.py:470` at zero net lines so it records each call once and ORs `ran` into `spliced`. The file stays at 700 lines.
6. Out-of-core: keep a sticky positive flag across batches in the text_redact accumulator.
7. Set `planned_backend=RUST_COMPANION` in the text_redact spec (`_operator_registry.py:162-172`). Keep `required_kernel=None` and `positive_kernel_evidence=False`. With `True`, an admitted idle unified column would be rejected (`execution/_unified_slice_evidence.py:125`), so M8 checks this.
8. Every route books the executed backend through `executed_backend(RUST_COMPANION, native_admitted=True, kernel_idle=not ran)`. The sequential `ColumnDecision` and the out-of-core `TextRedactColumnDecision` gain a `spliced: bool = False` field. Their `entry()` methods call `executed_backend()` for text_redact only, with `kernel_idle=not self.spliced`, when `self.native and ran` holds. A declined or companion-absent column (`backend=python_scalar`, built at `_sequential_native.py:204-211` and `_text_redact_native.py:197-204`) keeps `self.backend`, as section 5.6 requires. Other strategies keep their current label logic. The rule itself stays in `_chunked_evidence.py`; the two `entry()` methods only call it.
9. Label change this causes: an admitted sequential or out-of-core text_redact column that splices nothing in Rust (all-null, all-declined, E1 or E1b) moves from `rust_companion` to `arrow_python`. Existing-suite edits in S1c: retarget the shared OOC marker `install_marking` (`tests/parity/_ooc_text_redact_data.py:120-132`) from `native_text_redact` to `splice_text_redact` and make it return `ran`, so the OOC label assertions at `test_ooc_text_redact_native_routing.py:107, :179, :459, :481, :684` keep their meaning (:179 changes to `arrow_python`). In `test_phase_d_text_redact_seq.py`, tie `_SEQ_BACKEND` (:60) to the splice-entry probe, not `kernel_loads()`, so the T6 assertion at :420-427 expects `arrow_python` on a wheel without the additive entry (E1b). Unified and chunked already follow `executed_backend()` and move from `arrow_python` to `rust_companion` only for a column that spliced.

`_COMPANION_STRATEGIES` (`_chunked_evidence.py:59`) derives from the registry, so it gains `text_redact` without an edit. `_COMPILED_BACKENDS` in `pipeline/_route_summary.py:36` reads only specs with a `required_kernel`, so text_redact stays out of it and a route summary does not count text_redact as proof of a compiled run. That is today's behavior and S1c keeps it.

### 5.6 Label table after S1c (parent section 5.4)

| Case | Unified and chunked | Sequential | Out-of-core |
|---|---|---|---|
| A batch splices a real cell in Rust | `rust_companion` | `rust_companion` | `rust_companion` |
| Admitted, every batch idle (E1, E1b, all declined, all null) | `arrow_python` | `arrow_python` | `arrow_python` |
| Companion absent or source/config declined on nonempty input | route label and existing reason | `python_scalar` and existing reason | `python_scalar` and existing reason |
| Handler bypasses the sequential recorder | follows route admission | none, zero native calls, existing reason | follows route admission |
| No rows | route's existing empty behavior | none and route reason | none and route reason |

## 6. Slices

Each slice is R2, merges separately and starts from the merged previous slice. Write the named acceptance tests first, run them on the slice base and record the expected failures. Record the already-green legacy guards separately. Then implement, rerun and run the slice's mutations. Code gate: Codex and Dennis. Test depth: T0 per edit, T1 impact selection per commit, T2 on the exact gate head with the real companion built. S1b hits the full-suite escalation triggers for test config (census, F29 fixture, adapter registry) and a frozen contract (reason registry), so its gate also runs a full suite against the saved main baseline, plus `python scripts/release/reason_release_pin.py --check` and `python scripts/dev/registry_renumber.py --check --main origin/main` (`CONTRIBUTING.md:57`). S1c edits shared test fixtures (`tests/parity/_ooc_text_redact_data.py`), a full-suite escalation trigger, so its gate also runs a full suite on the merge head against the saved main baseline.

| Slice | Depends on | Content | Size | Gate evidence |
|---|---|---|---|---|
| S1b | S1a (#806) merged | Helper (5.1), offset guard (5.2), translator family dispatch and FPE delegate (5.3), five reasons (4.6), ratchet decreases (5.3), resolver fix (5.4), benchmark workers, fragment `changelog.d/text-redact-splice-reasons.md` naming the five codes | M, about one builder-day: 200-280 implementation lines, 250-350 test lines | AT-1, AT-1b, AT-2 wrapper, AT-3 wrapper, AT-3 capacity helper half, AT-3 detector offsets, AT-3 invalid output, AT-6 translation and fallback, AT-7 helper error, AT-9 Dell on the helper. Mutations M2, M3, M4, M7, M9, M10. |
| S1c | S1b and S1t merged | Route switch, old body deletion, `ran` transport, recorder, sticky out-of-core flag, registry label (5.5), existing regression suites, snapshots, docs, fragment `changelog.d/text-redact-rust-splice.md` | M, about one builder-day: 150-220 implementation lines, 250-350 test lines | AT-3 capacity through the routes, AT-5 text_redact, AT-5 predicate, AT-6 route outcomes, AT-7 route surfaces, AT-10 text_redact. Mutations M5, M8. |

**Activation boundary.** No production route calls the helper in S1b. Job use of the additive entry starts at the S1c head, which is the same head that first requires correct attribution in AT-5. A builder who finds a route call in the S1b diff stops: it is out of scope.

**S1c existing-suite edits** (parent section 8, re-anchored): direct helper callers in `tests/native/test_c6c_i_text_redact_kernel.py` and `test_c6c_ii_text_redact_rust.py:72` (keep the non-string case at :331); `tests/parity/test_phase_d_audit_no_legacy.py:482` text_redact parameter only, now marking an additive result after the probe; the all-null expectation at `test_ooc_text_redact_native_routing.py:179`; the real splice at `test_c6c_i_text_redact_chunked.py:70`; `tests/sentry/test_unified_backend_map.py:40` (`ARROW_PYTHON` to `RUST_COMPANION`); `tests/native/test_operator_tables_snapshot.py:86` (`"arrow_python"` to `"rust_companion"`) and :215 (add `"text_redact"` to the expected `_COMPANION_STRATEGIES` set). Run the `test_phase_d_text_redact_seq.py:179` config-bypass cases and `test_ooc_text_redact_native_real.py` as already-green guards. Run candidates-only fixtures on an explicitly legacy stub.

**Fragments.** `changelog.d/text-redact-splice-reasons.md` (S1b) names each code as an exact code span and states that no job uses them yet. `changelog.d/text-redact-rust-splice.md` (S1c) states that text_redact now splices in Rust on all four routes, that bytes do not change, and the per-route label changes in section 10 item 2. Format per `changelog.d/README.md`.

**Bench.** S1b updates `scripts/bench_text_redact.py`: the equivalence helper and a new Arrow splice worker call `splice_text_redact` directly; the baseline8 and new11 workers stay bound to their candidates paths; the oracle worker forces full Python. Each worker checks its expected entry on an untimed call. Record the Dell CPU, build SHA, wheel, fixture seed and ten samples in the PR body.

## 7. Placement

| Change | File | Size after |
|---|---|---|
| `splice_text_redact`, walk and assembly | `execution/native/_kernels_scalar.py` | about 480 at S1b, about 430 at S1c after the old body goes. Must stay under 600 at every head. |
| `_checked_splice_output`, repair scatter, `partition_detector_rows` | `execution/native/_text_mask_native_splice.py` | about 320. S2a reuses all three for text_mask. |
| Resolver fix | `execution/native/_text_redact_kernel.py:331` | about 436, net zero |
| Translator family | `execution/native/_crypto_ext.py:362`, `_fpe_ext.py:50` | `_crypto_ext.py` 536 to about 560; `_fpe_ext.py` about -8. FPE-CHECKSUM-NATIVE S2b keeps its new probe vectors out of `_crypto_ext.py`, so the combined total stays under 600. |
| Reasons | `reasons/runtime/_part3.py` (or `_text_splice.py` per section 4.6) | under 600 |
| Route switch and evidence (S1c) | the four call sites, `_operator_step.py`, `_sequential_native.py`, `_sequential_native_ops.py`, `_sequential_native_decisions.py` (112 lines), `out_of_core/_text_redact_native.py` (251 lines), `_operator_registry.py`, `native/__init__.py` | `_sequential_native.py` stays at 700; `_sequential_native_ops.py` at or below 600 |
| Unit tests | new `tests/unit/execution/native/test_text_redact_splice_helper.py` | within the module-size budget |

No new production module in `execution/native/`; the package fan-out stays at 55 (`tests/sentry/layout/test_package_fanout.py:36`). Run import-linter and the module-size sentry. No census, allowlist or cap increases.

## 8. Class table

| # | Class | Where it applies | Closing structure | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | boundary errors, E7, repair | fixed summaries from the registry; the splice family never reads the detail after `": "`; raise outside the handler | AT-7 injects a unique data sentinel in a known code and in an unknown exception and checks error text, warnings and Job.log | make the splice family echo the detail (AT-7 red) |
| 2 | Cleanup missing on an exit path | translated errors carry the raw exception | raise after leaving the `except` so cause and context are empty | AT-7 asserts `__cause__ is None` and `__context__ is None` | use `raise ... from exc` (AT-7 red) |
| 3 | State and concurrency | `ran` across batches, routes and chunks | OR fold per call; sticky flag per out-of-core column; chunked fold unchanged | AT-1b per-row marks, AT-5 both batch orders | keep only the last batch's `ran` (AT-5 red) |
| 4 | Route parity and silent fallback | post-probe failure, the four S1c routes | no retry inside the helper; one backend selector | AT-6 wrapper (S1b), AT-5 and AT-10 (S1c) | M4 catch and fall back (AT-6 red); M5 planned label always (AT-5 red) |
| 5 | Referential integrity | FK columns next to a text_redact payload | N/A: FK admission and staging are unchanged in S1b and S1c (S1t owns staging); AT-10 runs the sequential payload-next-to-key regression | AT-10 | n/a |
| 6 | Untrusted producer | the companion's returned pieces | `_checked_splice_output` validates shape, lengths, mask nulls and validity before repair, and nulls after scatter | AT-3 invalid output, one case per rule | skip the true-bit-on-null check (AT-3 red) |
| 7 | Check then use (TOCTOU) | probe result versus job call | the probe binds to the imported companion instance (`companion_compat`), and the job calls the bound callable, never a fresh attribute lookup | AT-6 swaps the module attribute after the probe and expects the bound entry | look the entry up again per call (AT-6 red) |
| 8 | Weak tests | parity alone hides a discarded Rust result | AT-1b marks each eligible output in an instrumented second run and requires the mark at the same position; AT-9 forbids list conversion | AT-1b, AT-9 | M7 list rebuild (AT-9 red); M3 shifted repair (AT-7 red) |
| 9 | Refactor drift | old body deletion, route switch, FPE translator delegate | S1c keeps byte parity on every route; the FPE delegate keeps `test_fpe_ext_loader.py` green unchanged | AT-10, existing FPE loader tests | let the fpe family map unknown codes to splice (FPE loader test red) |
| 10 | Frozen contract drift | masked bytes, reason registry, label | five new codes only, `since=UNRELEASED`; ratchets only decrease; fragments name the label change | AT-1, AT-10, registry sentries | M9 catalog-order expansion (resolver test red) |

Recurring-defect catalog checks: no new regex; exact integer versions are checked in S1a's probe; private imports go through the native package export; skips are recorded and the real-companion tests must execute (an all-skipped run fails the gate).

## 9. Acceptance tests

Each fails on its slice base unless marked already-green. IDs match the parent.

- **AT-1 (S1b).** Helper against the oracle handler. Every built-in, adjacent and overlapping spans, duplicate and unknown names, permutations, nulls, empty and long strings, both label modes, two literal tokens, overlap strings `12345-6789` and `-2283038836`. `detectors=()` keeps a known email and gives `ran=False`. `detectors=None` masks it. Pin the literal `[REDACTED:email]` independently of both callers.
- **AT-1b (S1b).** Wrap the bound entry after its probe. Uniquely identifiable rows across at least two batches. Record each slice and mask. In an instrumented second run, mark each eligible output and require each mark at the same output position. Every eligible row appears once in Rust output and every ineligible non-null row once in Python repair. Include nulls, empty strings, 0x1c to 0x1f and non-ASCII.
- **AT-2 wrapper (S1b).** Bytes and validity at batch sizes 1, 7, 65,536 and whole input, thread budgets 1 and 4.
- **AT-3 wrapper (S1b).** `string`, `large_string`, offset slices, uneven chunks, zero chunks, empty and all-null input. Integer, float and Boolean inputs keep Python stringification. A surrogate token: a no-match cell returns plain text. Label mode with the same token and a known email gives the detector label from Rust.
- **AT-3 capacity, helper half (S1b).** Lower the batching byte ceiling through the internal test seam used by S1a. Expand many short matches with a long token in one batch, and separately exceed the ceiling across fitting batches. Include an expanding declined row. Assert a `ChunkedArray` result with each chunk under the reduced ceiling, complete ordered bytes and nulls.
- **AT-3 detector offsets (S1b).** E1b on a pre-S0 wheel with the Python guard limit injected at 64 bytes. A spy on both legacy detectors proves the oversized row never reaches them. Expect one short token per email in order, with a null and a short email beside it.
- **AT-3 invalid output (S1b).** One injected case per rule in section 5.1 step 5, plus a forced bad null after scatter. Each raises `text_splice_output_invalid`.
- **AT-6 (S1b translation and fallback; S1c route outcomes).** Wrapper: a post-probe raise of each known code gives its registered error, an unknown code or a `TypeError` gives `text_splice_output_invalid`, and no Python retry happens (zero candidates calls after the raise). The FPE family returns an unknown FPE code unchanged and maps the two determinism codes as today. S1c: the unified coordinator reroutes the fault to the full-frame oracle; chunked, sequential and out-of-core propagate it.
- **AT-7 (S1b helper; S1c route surfaces).** Interleave eligible, null, distinct Unicode and ASCII controls (tab, NUL, DEL, CRLF). Ordered bytes match the oracle. Inject a unique data sentinel in a known-code detail and in an unknown exception. Require fixed messages, no sentinel in the error, warnings or Job.log, and no cause or context.
- **AT-9 (S1b).** Dell, WSL2, the parent section 1 fixture (120,000 mixed cells), release wheel from the S1a head. Probe before timing, warm up once in a fresh worker, time ten complete helper calls with `perf_counter`. Median elapsed seconds x 1,000,000 / 120,000 must be at most 3.0. Compare bytes and validity to full Python outside the timer. On an all-eligible call, forbid per-cell repair, `to_pylist` on input or output and list-backed `pa.array`.
- **AT-9b (S1b, CI).** Two parts, both in CI on every commit, so M7 fails without the Dell run. (a) Runtime: with a stub additive entry, patch module-level `pa.array` to raise on list input and call the helper on an all-eligible input. (b) Static: pyarrow types are immutable (`MonkeyPatch.setattr(pa.Array, "to_pylist", ...)` raises `TypeError` on pyarrow 24), so an AST test over `splice_text_redact`, its walk and assembly helpers and `_checked_splice_output` forbids `.to_pylist(` and `.to_pandas(` calls in those functions. Mutation M7b reintroduces a `to_pylist` call there and must fail part (b).
- **AT-5 (S1c).** Every case in section 5.6 on all four routes. Public `detectors: []`, token `<X>`, `mail a@b.com now` gives `mail <X> now` and `rust_companion` on each route with the current wheel. Absent companion, non-string decline, no rows, all-null and all-ineligible columns. Sequential invalid configs `{"token": 5}`, `{"detectors": "email"}`, `{"detectors": 7}`: unchanged bytes, none, zero native calls and the existing reasons (already-green guard).
- **AT-5 predicate (S1c).** Chunked text_redact with `when:` selecting a non-ASCII row with an email: masked bytes, unchanged unselected bytes, `arrow_python` and one activation. Zero selection: original bytes, `arrow_python`, no strategy entry. A selected no-match Python row: same bytes and backend, different counts.
- **AT-3 capacity through routes (S1c).** The parent's full route case with the real helper and the reduced ceiling at builder, scatter and consumer.
- **AT-10 (S1c).** One corpus on unified, chunked, sequential and out-of-core with the companion built: nulls, declines, both label modes, tie strings. Bytes, validity and schema metadata against the oracle route, plus the sequential payload-next-to-key FK regression.

Named mutations (run each alone against the passing tests, restore before the next, record the head and the failing assertion):

| ID | Mutation | Must fail | Slice |
|---|---|---|---|
| M2 | drop the detector id in `redaction_label` | AT-1 pinned literal | S1b |
| M3 | shift a repaired row by one position | AT-7 | S1b |
| M4 | catch a post-probe failure and use Python | AT-6 | S1b |
| M7 | rebuild eligible output with `pa.array` from a list | AT-9b (a) | S1b |
| M7b | call `.to_pylist()` on the eligible input in the helper | AT-9b (b) | S1b |
| M9 | expand `None` in catalog order | resolver unit test | S1b |
| M10 | process only the first input chunk | AT-3 wrapper | S1b |
| M5 | report the planned backend regardless of `ran` | AT-5 all-idle column | S1c |
| M8 | set `positive_kernel_evidence=True` | AT-5 idle unified column completes | S1c |

## 10. Frozen contracts and byte changes

No masked-byte change in either slice. AT-1 and AT-10 gate it.

Named changes:

1. **S1b.** Five new runtime reason identities (section 4.6), `since=UNRELEASED`. Release prep owns the registry version, manifest, consumer contract and release fixture (`CONTRIBUTING.md:57`). No public Python signature changes; `splice_text_redact` is private to the native package. The FPE translator keeps its name and behavior.
2. **S1c.** The text_redact planned backend moves from `arrow_python` to `rust_companion`. Executed backend, per route: unified and chunked report `rust_companion` for a column that spliced in Rust (was `arrow_python`) and keep `arrow_python` for an idle admitted column. Sequential and out-of-core report `arrow_python` for an idle admitted column (was `rust_companion`) and keep `rust_companion` for a column that spliced. This is a run-card change, not a byte change. The S1c fragment states both directions per route.

The ABI stays `decoy-native-abi-3` (`_crypto_ext.py:359`). The additive entry is a capability under rule 4 of `docs/native/supported-matrix.md:119`, bound by S1a's probe.

## 11. Pre-mortem

- The S1b helper reaches a route by accident and runs Rust under an `arrow_python` label. Guard: section 6 activation boundary; Dennis checks the S1b diff for any call site change.
- S1c lands before S1t and a route receives a `ChunkedArray` it cannot assemble. Guard: S1c's dependency on S1t is hard; the S1c builder checks S1t is merged before starting.
- The FPE delegate changes FPE error behavior. Guard: `tests/native/test_fpe_ext_loader.py` runs unchanged, and AT-6 covers the fpe family.
- FPE S1 (#803) and S2b also edit `_fpe_ext.py`. The hunks do not overlap (#803 edits `run` near :133-157; S1b edits the translator at :50). Census keys use the function name, not the line, so a rebase does not move them.
- A builder raises a ratchet to get green. Every ratchet edit in this plan is a decrease; any increase fails the gate.
- `_part3.py` passes 600 lines because another row added reasons first. Section 4.6 gives the fallback module.

## 12. Owner questions and dependencies

- **OWNER CALL (taken: let S1b merge before S1t).** The parent orders S1t before S1b. S1b is helper-only, so the order does not affect jobs. The non-breaking choice is to let S1b merge when S1a merges and hold S1c for S1t. Recommended and taken.
- **OWNER CALL (taken: ABI order with FPE).** FPE-CHECKSUM-NATIVE S2b moves the ABI to `decoy-native-abi-4`. These slices stay on abi-3 and do not touch the tag. If abi-4 merges first, S1b and S1c rebase onto it with no change; this row's S2b skew test then asserts a clean load refusal for an abi-3 wheel instead of a run. Recorded for the parent's S2b.
- Not decided here: whether text_mask evidence defers to ROUTE-LABEL-TRUTH (parent section 12). It does not affect S1b or S1c.

Dependencies: S1b needs #806 merged. S1c needs S1b and S1t merged. S1t has no builder yet and needs one before S1c can start.
