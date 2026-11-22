Status: plan (revision 1, 2026-11-22)

# TEXT-REDACT-RUST-SPLICE: text_redact detects and splices spans in Rust, over Arrow, on every native route

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: TEXT-REDACT-RUST-SPLICE (CLI `docs/roadmap/groups/mask.md:32`, group mask, 1.0.x, not started): "reusing detect and splice in text_mask.rs ... Output bytes do not change." V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, line 68 and rank 10). Engine only. The CLI gets the change through its next engine pin bump.

Anchors: a path with no prefix is under `src/decoy_engine/` in decoy-engine. `crate/` is the Rust crate `decoy-engine-native/src/`. Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `performance.md`, `api-and-compatibility.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where things go").

Risk: R2 (a masking hot path moves to a new compiled entry point; a wrong span is a leak; output must stay byte-identical). Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

Owner direction (2026-11-22): fastest path by default; each column runs its own path; faster wins even when bytes change, if each change is named. This row needs no byte change. The measured Rust path matches the oracle exactly (section 1), so the roadmap text "Output bytes do not change" holds.

## 1. Frame

`text_redact` is admitted on the native routes as an Arrow-Python operator (`execution/_operator_registry.py:162-172`: `planned_backend=ARROW_PYTHON`, `required_kernel=None`). Every native route calls one function, `native_text_redact` (`execution/native/_kernels_scalar.py:149`):

- unified slice and chunked native step: `execution/native/_operator_step.py:343`;
- sequential route: `execution/_sequential_native_ops.py:474`;
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
- (c) a route label that says Rust ran. `executed_backend` (`execution/native/_chunked_evidence.py:116`) reports `arrow_python` for text_redact and text_mask, because their step returns `ran=None` (`_operator_step.py:347` comment). After this row, Rust does all the work for eligible cells, so `arrow_python` would understate the route.

### Overlap with RUST-DATE-TEXT (1.2)

RUST-DATE-TEXT (`mask.md:34`) owns full-Unicode text paths and multi-thread text kernels through `native_threads` (its R10 and R11). Today a non-ASCII cell declines to Python (`_text_redact_kernel.py:74` `is_ascii_safe`), and it still does after this row. This row releases the GIL around a single-threaded loop, because the input is Arrow and no Python object is touched. Splitting a batch across threads stays with RUST-DATE-TEXT. The new entry point takes `native_threads` now and treats any value as 1, so RUST-DATE-TEXT changes the body, not the signature.

## 2. Established solutions

Search run: span redaction engines (Microsoft Presidio anonymizer operators and conflict resolution; Google DLP `ReplaceWithInfoTypeConfig`); Rust Arrow string building (arrow-rs `StringBuilder`); the engine's own text_mask path.

- Presidio applies one model: detectors give `(start, end, entity)` spans, a conflict step keeps non-overlapping spans, and an operator per entity replaces each span ("replace" with a fixed value, or the default `<ENTITY_TYPE>` label). Google DLP's `ReplaceWithInfoTypeConfig` is the same label form. So `token` and `label_token` are one splice loop with a replacement string per entity, not two code paths. Source: Presidio anonymizer docs (microsoft.github.io/presidio/anonymizer).
- arrow-rs `StringBuilder::with_capacity` builds a string column in one pass. The engine already uses it in `crate/arrow_ffi.rs:110` `export_string_array` and imports arrays with `import_array` (`crate/arrow_ffi.rs:54`).
- The engine's `detect_splice_cell` already reproduces the oracle merge and has text_mask parity tests. This row extends it. It does not write a second sweep.

### Reuse inventory

- `crate/text_mask.rs:102` `detect_splice_cell`, `:62` `splice_cell`, `:52` `push_gap`: changed in place (section 5.1), not copied.
- `crate/text_redact/` (`candidates_for_cell`, `is_eligible`, `CATALOG_LEN`, `SUPPORTED_IDS`, catalog version 2): unchanged.
- `crate/arrow_ffi.rs` `import_array`, `export_string_array`: reused for the Arrow boundary.
- `execution/native/_text_redact_kernel.py`: `load_text_redact_kernel` (returns None when the companion is absent or skewed), `requested_rust_ids`, `is_ascii_safe`, `CATALOG_VERSION`: reused. `merge_text_redact_spans` stays for cells that decline.
- `execution/_strategies/_text_redact.py:198` `_splice` and `detection.detectors.iter_spans`: stay as the oracle and as the per-cell fallback.
- `StepResult.ran` (`execution/native/_operator_step.py:256`) and `executed_backend`: reused for the label. No new label rule.

## 3. Guarantee and non-goals

After this row:

1. On every native route (unified slice, chunked native, sequential, out-of-core), a `text_redact` cell that is a non-null ASCII-safe string, in a column that requests only Rust-supported detectors, is detected, merged and spliced by one Rust call per batch. Its output is byte-identical to the pandas oracle (`TextRedactHandler.run`) for `label_token` true and false, any `token`, and any detector list and order, including duplicates.
2. Every other cell (null, not ASCII-safe) and every other column (a detector outside `SUPPORTED_IDS`, custom or extra detectors) takes today's Python path inside the same function. Its bytes do not change.
3. `text_mask` keeps its bytes. Its Rust entry moves onto the same core and the same Arrow boundary.
4. On the Rust path, input and output cross the boundary as Arrow arrays: no `to_pylist`, no `pa.array(list)`.
5. The executed backend is `rust_companion` for a text_redact or text_mask column when the Rust entry handled at least one cell of it, and `arrow_python` when it handled none (companion absent, or every cell declined). The run card and the `docs/` route table name both cases.
6. With the companion absent or skewed, output is unchanged and the route is native Arrow-Python, as today.

Non-goals: full-Unicode cells and multi-thread splitting (RUST-DATE-TEXT, 1.2); NER (stays refused natively, `execution/native/_operator_config_rejections.py:291` `text_redact_ner_not_native`); new detectors; the pandas oracle handler's own loop (it stays the reference); text_mask strategies other than redact and passthrough (they keep their Python path).

## 4. Enumerations

### 4.1 Routes

| Route | Entry | After this row |
|---|---|---|
| unified slice | `_operator_step.py:343` `native_text_redact` | same call, new body |
| chunked native | same step | same |
| sequential | `_sequential_native_ops.py:474` | same |
| out-of-core | `out_of_core/_text_redact_native.py:224` | same |
| pandas full frame (native declined) | `TextRedactHandler.run` | unchanged (oracle) |

One function body changes, so the four native routes move together. No route-specific code.

### 4.2 Exit paths of the new call

| # | Condition | Result |
|---|---|---|
| E1 | companion absent or catalog skew (`load_text_redact_kernel` returns None) | whole column on the Python path, `ran=False` |
| E2 | a requested detector outside `SUPPORTED_IDS`, or custom or extra detectors | whole column on the Python path, as today, `ran=False` |
| E3 | null cell | null out, in place |
| E4 | non-null cell that is not ASCII-safe | Rust marks it declined; the Python path runs for that cell only |
| E5 | eligible cell | Rust output |
| E6 | Rust boundary error (catalog mismatch, unknown id, length mismatch, unsupported array type) | a coded error from the boundary, mapped through the existing translation in `_text_redact_kernel.py`; never a silent fallback |
| E7 | output length or null mask differs from the input | the existing `_checked_batch` guard pattern raises |

### 4.3 Codes

No new reason codes. The labels are the existing `rust_companion` and `arrow_python`. If ROUTE-LABEL-TRUTH (`plan/route-label-truth`) merges first, its per-column decline record carries E1 and E2. If a decline code for E1 or E2 is not yet in `reasons/route`, the S1 builder registers it once in `reasons/route/_added.py` and nowhere else.

### 4.4 FK shapes

N/A: text_redact is not an FK key strategy and this row changes no admission, so a text_redact column on an FK key is refused or routed exactly as today.

### 4.5 Fields

| Field | Values | Handling |
|---|---|---|
| `detectors` | absent (all built-ins), a list, an empty list | absent and lists map through `requested_rust_ids`; an empty list means zero detectors (cells pass through), same as the oracle |
| `token` | any string | `Replace(token)` |
| `label_token` | true, false | `Replace("[REDACTED:<id>]")` per index, or `Replace(token)` |
| `ner` | set | refused natively (unchanged) |
| custom or extra detectors | set | E2, whole column on the Python path |

### 4.6 Output surfaces

| Surface | Change |
|---|---|
| masked output column | none (byte-identical) |
| `quality_metrics` route evidence and the run card | executed backend `rust_companion` when Rust ran |
| `docs/` route table | text_redact and text_mask rows say Rust for ASCII-safe cells, Python per cell otherwise |
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

A new pyfunction in `crate/text_mask.rs`: `text_span_splice(values, *, detector_ids, outs, passthrough_unmatched, catalog_version, native_threads=None)`. It returns a pair: the spliced `pa.string()` array, and a `declined` boolean array (true where a non-null cell is not ASCII-safe; the string array holds null there).

- `values` comes in through `import_array`. `string` and `large_string` are accepted. Any other type raises `unsupported_type`.
- The output uses `StringBuilder::with_capacity(len, input_bytes + slack)`.
- The loop runs inside `py.allow_threads`. `native_threads` is accepted and treated as 1.
- `text_mask_detect_splice` stays as a thin list wrapper over the same core until S2 moves text_mask, then S2 deletes it.

### 5.3 Python side

`native_text_redact` becomes:

1. E1 or E2: today's code, `ran=False`.
2. Otherwise one `text_span_splice` call per 65,536-cell batch (the batch size already in `_kernels_scalar.py`), on the Arrow array.
3. If `declined` has any true value: take the declined cells with `pc.filter`, run today's Python fallback on them only (the code at `_kernels_scalar.py:183`), and put them back with `pc.replace_with_mask`.
4. Return the output with `ran=True`.

`native_text_redact` returns a `(array, ran)` pair. The four callers pass `ran` into `StepResult` or into their route evidence; today they hard-code `None`.

`native_text_mask` takes the same shape in S2, where `plan_native_splice` (`execution/native/_text_mask_native_splice.py`) already decides that a config is the redact and passthrough shape.

### 5.4 Route label

`OperatorSpec` for `text_redact` and `text_mask` (`_operator_registry.py:162`, `:173`): `planned_backend=RUST_COMPANION`, `positive_kernel_evidence=True`, `required_kernel=None` (the operator still runs without the companion). `executed_backend` then gives `rust_companion` when `ran` is true and `arrow_python` when it is false, with no new rule. The chunked fold `merge_executed_backend` (`_chunked_evidence.py:128`) already keeps `rust_companion` if any chunk ran Rust.

Consistency with ROUTE-LABEL-TRUTH: that plan reads the executed backend per column from these same fields and adds the decline record. This row changes only the spec values and the `ran` evidence.

## 6. Placement

| What | Where | CODEMAP line | Beside |
|---|---|---|---|
| `SpanOut` core and `text_span_splice` | `decoy-engine-native/src/text_mask.rs` (341 lines, about +90) | native crate, by kernel | `text_redact/` |
| bridge protocol for `text_span_splice` | `execution/native/_text_mask_native_splice.py` (`SpliceKernel`) | "Native companion bridge", fan-out freeze at 55 | no new module |
| `native_text_redact` body | `execution/native/_kernels_scalar.py` (384 lines, about +30) | same | - |
| spec values | `execution/_operator_registry.py` | "Pipeline spine and routes" | two field edits |
| tests | `tests/unit/execution/native/test_text_span_splice.py`; Rust tests in `text_mask.rs` | "Unit tests" | `tests/unit/execution/native/` |
| docs | `docs/` route table rows for text_redact and text_mask; changelog fragment | docs | no `Breaking:` line |

No new Python module. `execution/native/` stays at its freeze.

## 7. Defect classes

### 7.1 Plan-contract classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | boundary errors and the decline path could echo cell text | errors carry a registered code and counts only; the mapped Python error is raised after the `except` closes | AT-7 | put the cell into the `unsupported_type` message (AT-7 red) |
| 2 | Cleanup missing on an exit path | none | N/A: no resource is acquired; arrays are owned by Arrow | n/a | n/a |
| 3 | State and concurrency | GIL released around the loop | the loop reads only the imported Arrow buffers and owned Rust values; no Python object is touched while released | AT-2 (threads 1 and 4) | read a Python list inside `allow_threads` (does not compile; reviewer check) |
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
| AT-1 | Oracle parity: a generated corpus (each supported detector, overlaps, adjacent spans, duplicate detector ids, all orders of a three-detector subset, empty strings, long cells, nulls) through `native_text_redact` and through `TextRedactHandler.run`, `label_token` true and false, two tokens; outputs equal | passes today (both run Python), kept as the guard; the fail-before is AT-1b | S1 |
| AT-1b | Same corpus: the Rust entry handled every eligible cell (`ran` true, decline count 0 on ASCII input) | `ran` is None today | S1 |
| AT-2 | Batch and thread invariance: one column at batch sizes 1, 7, 65,536 and whole, `native_threads` 1 and 4; outputs equal | no `text_span_splice` today | S1 |
| AT-3 | Arrow boundary: `string` and `large_string` in; nulls stay null in place; empty and all-null arrays; output type `pa.string()`; an `int64` array raises `unsupported_type` | no entry today | S1 |
| AT-4 | text_mask bytes unchanged on the new core: existing text_mask native-splice tests plus a redact and passthrough corpus through `text_span_splice` | no entry today | S1 (core), S2 (wired) |
| AT-5 | Executed backend: with the companion, `rust_companion` for text_redact on the unified slice, chunked, sequential and out-of-core routes; without it, `arrow_python`; an all-non-ASCII column gives `arrow_python` | always `arrow_python` today | S1 (text_redact), S2 (text_mask) |
| AT-6 | A forced catalog-version mismatch, a bool `catalog_version` and an unknown detector id each raise their coded error and do not fall back to Python | no entry today | S1 |
| AT-7 | Non-ASCII decline: output equals the oracle; no cell text appears in any warning, error or log record; the mapped error has no cause or context | no entry today | S1 |
| AT-8 | Rust unit tests: `label_token` replacement per index; `SpanOut::Verbatim` keeps the span; ties on (start, length) keep requested order | no `SpanOut` today | S1 |
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

## 10. Byte changes

None. AT-1 is the proof. The changelog fragment says the text_redact and text_mask route label changes from `arrow_python` to `rust_companion` when the companion runs them. That is a label change, not an output change.

## 10a. Frozen contracts

- `docs/compatibility-contract.md` freezes masked output bytes for shipped strategies. This row keeps them (AT-1).
- The companion ABI version moves (a new pyfunction). The bridge's skew check already turns an old companion into E1, so an engine with a stale wheel stays correct and slow.
- The backend vocabulary (`rust_companion`, `arrow_python`) is unchanged; only which value text_redact and text_mask report changes. Additive for consumers that read the label.

## 10b. Pre-mortem

- A tie in the merge orders differently in Rust for a detector list with duplicates. AT-1 includes duplicates and all orders of a three-detector subset; M1 proves the test sees ordering.
- A cell that Python treats as ASCII-safe but Rust does not (or the reverse) splices differently. Both sides use the same `is_eligible` rule today; AT-7 runs a corpus of edge characters (tab, DEL, NUL, CRLF) through both.
- `large_string` input from a Parquet source arrives on a route that used to see `string`. AT-3 covers both types.
- The decline scatter costs more than it saves on a mostly non-ASCII column. That column was slow before too; AT-9 is for ASCII text. RUST-DATE-TEXT removes the decline.
- The text_mask label change confuses a reader of old run cards. The changelog fragment names it.

## 11. Slices

| Slice | Content | Size | Gate |
|---|---|---|---|
| S1 | Rust `SpanOut` core, `text_span_splice`, Rust tests; `native_text_redact` on the new entry with decline scatter; `ran` threaded through the four callers; text_redact spec label; AT-1 to AT-3, AT-5 to AT-9; companion ABI bump and the engine repin checklist | M: about 250 lines Rust and Python, 300 lines tests | Codex and Dennis; T2 on the native and text_redact selection with the companion built |
| S2 | `native_text_mask` redact and passthrough configs on `text_span_splice`; delete the `text_mask_detect_splice` list wrapper; text_mask spec label; AT-4, AT-5 for text_mask; docs route table | S: about 80 lines, 120 lines tests | Codex |

Both slices fit before the 2026-12-15 engine-gap deadline.

## 12. Open questions for the owner

- Q1: The text_mask label change rides in S2 of this row (recommended, because the spec fields move with the kernel), or waits for ROUTE-LABEL-TRUTH? Recommended: here.

No other owner decision: no byte change and no new feature.
