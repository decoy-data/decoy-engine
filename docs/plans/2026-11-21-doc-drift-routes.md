Status: plan

# DOC-DRIFT-ROUTES: route docs that disagree with the code (record section 7, items 1 to 5)

Owner: Cam. Author: Opus plan agent. Date: 2026-11-21. Roadmap row: DOC-DRIFT-ROUTES (CLI `docs/roadmap/groups/run.md:27`). Source record: `docs/records/2026-11-19-engine-speed-and-route-completeness.md` (engine #715), section 7. Item 6 is a CLI roadmap question (record Q5) and item 7 is already fixed in the roadmap, so this plan covers items 1 to 5.

Anchors: all paths are in this repository (decoy-engine) unless marked `C:` (decoy CLI). Read at engine `origin/main` `035543388` and CLI `origin/main` `8d17419c`. Every item below was re-checked at that head: all five drifts are still present.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`, `documentation.md` (records stay as history; current docs are corrected), `verification.md`, `proportionality.md`, `scope-discipline.md`, `testing.md` (full-suite triggers), `profiles/local-operations.md`, `workspace-and-vcs.md`. Engine `CODEMAP.md` "Where Things Go".

Risk: R1 (docs and Rust doc comments only; no behaviour change). Plan review: one round, Codex. Code gate: Codex only.

## 1. Frame

### 1.1 Evidence per item (re-anchored at `035543388`)

| # | Doc and line | What it says | What the code does |
|---|---|---|---|
| 1a | `docs/execution-backends.md:78` (sequential table), `:201`, `:238-241` | `group_key` has no SEQ native admission | SEQ registers a native op: `GROUP_KEY: group_key_op(load_raw_hex)` (`src/decoy_engine/execution/_sequential_native.py:158`), admission `decide_group_key` (`src/decoy_engine/execution/_sequential_native_group_key.py`, reads the sibling column) |
| 1b | `docs/records/2026-10-16-d-audit-compute-matrix.md:37`, `:71` | same | same |
| 2 | `docs/execution-backends.md:95` (out-of-core table), `:199`, `:234-235` | OOC `text_mask` is a Python per-cell loop | native: `native_text_mask_array` is imported at `src/decoy_engine/execution/out_of_core/_mask_group_c.py:99` and used when `text_mask_native` is set (`:224-227`); kernel module `src/decoy_engine/execution/out_of_core/_text_mask_native.py` |
| 2b | `docs/records/2026-10-16-d-audit-compute-matrix.md:70` | same | same |
| 3 | `docs/records/2026-09-30-rust-coverage-evidence-audit.md` headline 2 | the chunked executor has no production caller; categorical, bucket_perturb, group_key and date_shift are vetoed | the chunked dispatcher is on by default (`run_pipeline(..., chunked_dispatcher_enabled: bool = True)`, `src/decoy_engine/execution/_pipeline.py:141`); `CHUNKED_ROUTE_VETOED_STRATEGIES` is empty (`src/decoy_engine/execution/native/_requirements.py:145`) |
| 4 | `docs/relationships.md:270-278` | "Cross-table FK cycles support (Cam decision pending)" | decided: V1 keeps the automatic full-frame fallback; first-class cycle support is a V2 candidate (record section 2.2; `C:docs/roadmap/groups/run.md:63`) |
| 5a | `decoy-engine-native/src/lib.rs:1-9` | the companion exports `abi_version`, `derive_batch`, `derive_index_batch`; "everything else stays pure Python" | it also exports `resolve_native_threads`, `derive_hex_raw_batch`, `fpe_transform_batch` (`decoy-engine-native/src/arrow_ffi.rs:608-614`), eight `text_redact_*` functions (`text_redact/pyboundary.rs:179-186`) and `text_mask_splice_spans` (`text_mask.rs:245`) |
| 5b | `decoy-engine-native/src/threads.rs:1-19` | the pool is built but "execution stays sequential"; wiring is "Task 1.5's job" | the shared pool runs the batch loops: `shared_native_pool()` is called at `decoy-engine-native/src/batch/ranges.rs:52` and `decoy-engine-native/src/fpe.rs:442` |

### 1.2 The guarantee

- G1. Each current doc in the table (`docs/execution-backends.md`, `docs/relationships.md`, the two Rust module docs) states what the code does at the merge head, with a file reference.
- G2. The two records keep their text. Each gets one dated correction note under its `Status: record` line that names the stale claim and points at the current doc. Records are history (`documentation.md`), so they are not rewritten.
- G3. No source line other than Rust `//!` doc comments changes. No output, no test and no public name changes.

Non-goals: a sentry that checks route tables against the operator registry (Q1); record item 6 (CLI generation tiers, owner Q5); the `Status:` header on `docs/execution-backends.md` (not drift).

## 2. Established solutions

N/A: a doc correction needs no design. The record-correction note follows the engine's own practice of dated notes on records (for example the revision notes in `docs/plans/2026-11-20-24f-interior-bin-floor.md` section 15).

## 3. Edits

1. `docs/execution-backends.md`
   - Sequential table (`:78`): remove `group_key` from the shared-handler row and add a row: "`group_key` | native raw-hex kernel when the sibling column is admitted (`_sequential_native_group_key.py`); else the shared handler | dedicated Python".
   - Qualification row (`:201`): replace "SEQ has no native admission." with the SEQ admission rule from `decide_group_key`.
   - Bullet `:238-241`: drop `group_key` from the "no SEQ native admission" list.
   - Out-of-core table (`:95`): "`text_mask` | compiled span kernel (`out_of_core/_text_mask_native.py`); NER configs stay Python | excluded".
   - Qualification row (`:199`) and bullet `:234-235`: say OOC text_mask runs the span kernel, NER stays Python.
2. `docs/records/2026-10-16-d-audit-compute-matrix.md`: correction note "Correction 2026-11-21: since this record, SEQ `group_key` and out-of-core `text_mask` have native paths. See `docs/execution-backends.md` for the current table."
3. `docs/records/2026-09-30-rust-coverage-evidence-audit.md`: correction note "Correction 2026-11-21: headline 2 is out of date. The chunked dispatcher is the default lane (`chunked_dispatcher_enabled=True`) and no strategy is vetoed (`CHUNKED_ROUTE_VETOED_STRATEGIES` is empty). The current state is in `docs/records/2026-11-19-engine-speed-and-route-completeness.md`."
4. `docs/relationships.md:270-278`: rename the paragraph "Cross-table FK cycles (decided for V1)". Text: a mutual cycle runs on the full-frame route through the automatic fallback; that is the V1 behaviour; first-class support on the bounded routes is a V2 candidate. Keep the link to the backlog guide.
5. `decoy-engine-native/src/lib.rs:1-9`: list the exports by group (hash, index, raw hex, FF1, text redact spans, text mask splice, thread resolver, ABI tag) and drop "Everything else the engine does stays pure Python". Replace it with one sentence: the engine keeps a pure-Python oracle for every kernel.
6. `decoy-engine-native/src/threads.rs:1-19`: replace the Task 1.3 and 1.5 history with the current fact: `shared_native_pool` is the one process pool, sized by the resolved budget, and the batch loops (`batch/ranges.rs`, `fpe.rs`) run on it.

Size: about 60 changed lines in 6 files.

## 4. Behaviour

| Case | Before | After |
|---|---|---|
| Reader of `execution-backends.md` asks "is SEQ group_key native?" | no | yes, with the admission rule |
| Reader asks "is OOC text_mask native?" | no | yes, NER excepted |
| Reader of the 2026-09-30 record | stale headline 2 | correction note on top |
| Reader of `relationships.md` | decision pending | decided for V1 |
| `cargo doc` of the companion | stale module docs | current |
| Any run | unchanged | unchanged |

## 5. Failure modes

| Case | Behaviour |
|---|---|
| A test reads `docs/execution-backends.md` | `tests/unit/execution/pipeline/test_lifecycle_generate.py:236-250` reads only the "Advisory job estimate and lifecycle peak" section; this plan does not touch it (AT-3) |
| Rust doc comment breaks `cargo doc` or `clippy` | the native-companion workflow runs on `decoy-engine-native/**`; AT-4 |
| Line numbers move before the build | the builder re-anchors from the quoted text, not the numbers |

## 6. Choke point and sentries

No new rule: docs only. A doc-claim sentry is Q1.

### 6.1 Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | none | N/A: doc text only, no runtime message changes | n/a | n/a |
| 2 | Cleanup on exit path | none | N/A: no code path changes | n/a | n/a |
| 3 | State and concurrency | none | N/A: the threads.rs edit is a doc comment; the pool code is unchanged | n/a | n/a |
| 4 | Route parity | route tables in `execution-backends.md` | N/A: no code; each corrected cell cites the module that admits it | AT-1 | n/a |
| 5 | Referential integrity | the cycle paragraph | N/A: no code; the text matches the shipped fallback | AT-1 | n/a |
| 6 | Untrusted producer | none | N/A: no new input | n/a | n/a |
| 7 | Check then use (TOCTOU) | none | N/A: no file read is added | n/a | n/a |
| 8 | Weak tests | the claim "the doc now matches" | AT-1 greps each corrected claim against the cited code line at the merge head | AT-1 | n/a |
| 9 | Refactor drift | Rust files touched for comments only | N/A: AT-2 shows the diff has only `//!` lines in `.rs` files | AT-2 | n/a |
| 10 | Frozen contract drift | none | N/A: no public surface, output or compat text changes | n/a | n/a |

### 6.2 Enumerations

#### Exit paths

- N/A: docs only, no code path is added or changed.
- The Rust edit is `//!` lines only (AT-2), so no exit path in `decoy-engine-native/src/threads.rs:325` changes.

#### Routes

- SEQ: group_key cell (`src/decoy_engine/execution/_sequential_native.py:158`).
- Out-of-core: text_mask cell (`src/decoy_engine/execution/out_of_core/_mask_group_c.py:224-227`).
- Native chunked: the record note (`src/decoy_engine/execution/native/_requirements.py:145`).

#### FK shapes

- Cross-table cycles: the only FK shape these edits describe (`docs/relationships.md:270-278`).
- N/A for every other shape: no FK text changes.

#### Fields

- N/A: no config, result or record field changes.
- N/A: no reason code changes.

#### Output surfaces

- N/A: no runtime output changes.
- Rendered docs and `cargo doc` output change (text only).

## 7a. Reuse inventory

| Need | Reused | Changed |
|---|---|---|
| Current route facts | record `2026-11-19` section 2 | none |
| Correction note form | dated note under `Status: record` | two notes |

## 7. Acceptance tests, red first

- AT-1 (fails on `035543388`, passes after): `git grep -n "SEQ has no native admission" -- docs/execution-backends.md` returns nothing; `git grep -n "Cam decision pending" -- docs/relationships.md` returns nothing; `git grep -n "stays pure Python" -- decoy-engine-native/src/lib.rs` returns nothing; `git grep -n "Task 1.5's job" -- decoy-engine-native/src/threads.rs` returns nothing; each record has a line starting "Correction 2026-11-21".
- AT-2: `git diff origin/main -- '*.rs' | grep '^[+-][^+-]' | grep -v '^[+-]//!'` is empty.
- AT-3: on a VM, `~/bin/vm-run engine <wt> '$PY -m pytest tests/unit/execution/pipeline/test_lifecycle_generate.py -q'` passes.
- AT-4: the PR's native-companion workflow (`cargo fmt --check`, `clippy`, `cargo test`) is green.
- AT-5: `plan-lint` and the docs build (`sphinx -W`, as engine CI runs it) pass.

## 8. Placement

| File | Directory | CODEMAP "Where Things Go" line |
|---|---|---|
| `execution-backends.md`, `relationships.md` | `docs/` | "Feature and contract docs" |
| two records | `docs/records/` | "Plans, decisions, records" |
| `lib.rs`, `threads.rs` | `decoy-engine-native/src/` | the companion crate (no CODEMAP row; existing files only, no new file) |
| this plan | `docs/plans/` | "Plans, decisions, records" |

No new file in the build.

## 9. Frozen contracts touched

None. Full-suite trigger: no (docs and Rust doc comments; no test, fixture, lock or contract change). Gate: T1 is the doc-reading test (AT-3) plus the docs build and the companion workflow.

## 10. Slices

| Slice | Repo | Content | Size | Risk | Gate |
|---|---|---|---|---|---|
| D1 | engine | the six edits in section 3, one changelog-free docs PR (`docs(routes): ...`) | about 60 lines, 6 files | R1 | Codex |

After merge: CLI row 27 state to DONE with the PR number.

## 11. Stop lines for builders

- Do not rewrite a record body; add the correction note only.
- Do not touch Rust code lines; doc comments only.
- Do not add item 6 (CLI generation tiers); it waits on owner Q5.
- Stop and report if any cited code line no longer says what section 1.1 says.

## 12. Owner questions (recommended option first)

1. Q1. Add a sentry that derives the route tables in `docs/execution-backends.md` from the operator registry and the SEQ and OOC op tables, so this drift cannot recur? Recommended: not in V1. The row is docs only, and doc drift does not meet the V1 bar. Record a V2-LOG line.

## 13. Pre-mortem

- The builder edits only the table rows and misses the qualification rows and bullets: section 3 lists every line, and AT-1 greps the phrases.
- The Rust doc edit trips `clippy::doc_markdown` or `rustdoc` link checks: AT-4.
- A later merge moves line numbers: re-anchor by quoted text.

## 14. Sources

- Record `docs/records/2026-11-19-engine-speed-and-route-completeness.md` sections 2.2 and 7.
