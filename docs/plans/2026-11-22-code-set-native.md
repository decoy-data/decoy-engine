Status: plan (revision 6, 2026-11-24; S1 only with a bounded memo, S2 to re-plan)

# CODE-SET-NATIVE: code_set masks once per distinct value on the handler routes, with a bounded memo

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22, reworked 2026-11-24. Roadmap row: CODE-SET-NATIVE, from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, line 76). The row is a 1.0 row in the CLI roadmap `docs/roadmap/groups/mask.md`. Engine only.

Source anchor: engine main `9f7bb1f4a`. Every file this plan touches is unchanged between that commit and the plan branch. Paths without a prefix start at `src/decoy_engine/`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `performance.md`, `security.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md`.

Risk: R2 (masking output on every handler route). Plan review history: Dennis r1 GO-WITH-FIXES, Codex r1 NO-GO, codex-fix to rev 4, Codex r2 NO-GO, Opus rework to rev 5, Codex r3 NO-GO, owner split to rev 6 (S1 goes ahead, S2 re-plans). Code gate: Codex and Dennis.

## Changes in revision 6

The owner split the plan after Codex round 3. This revision covers S1 only. S2 (out-of-core admission) is marked "re-plan" in section 12, and Codex r3 findings 2 to 4 are listed there as its design inputs. This plan does not design the S2 fix.

| Codex r3 item | Resolution in rev 6 |
|---|---|
| 1 V1: the memo keeps every distinct input string alive. 24,000 distinct strings of about 4 KiB each raised `MemoryError` after 21,845 inputs with 24 MiB of headroom, where the base loop completed | The memo has two caps, named constants in `_code_set.py`: `_MEMO_MAX_ENTRIES = 65_536` and `_MEMO_MAX_KEY_BYTES = 8 * 1024 * 1024` (8 MiB of retained key bytes, measured with `sys.getsizeof(key)`). Before an insert, if the insert would pass either cap, the memo stops taking new entries for the rest of the call. Existing entries are still used. A value that is not in the memo gets the scalar call, as today. Output is byte-identical under and over the caps (5.1). Guarantee 1 is qualified (section 3). New AT-5 (the Codex 24k x 4 KiB case completes, and the memo's extra peak stays under the byte cap plus a fixed slack) and AT-6 (equal output under and over both caps, with call counts that prove the fallback). New mutations M8 and M9 |
| 2 to 4 V1: S2 wiring (loader-backed schemas, capacity and estimate, declared casting and staging order) | S2 moved out of this revision. Section 12 marks it "re-plan" and lists the three findings as design inputs. AT-3, M4, M5 and the `pandas_text_columns` design are removed from this plan and go to the re-plan |
| Non-blocking: one row-error producer | 5.1 resolves the reason from the failed memo or from the scalar call, then appends through one `RowError` site |
| Non-blocking: AT-1 fixtures must suit their boundary | AT-1 is split by boundary: mixed-object, surrogate and chapter cases run at `CodeSetHandler.run`; route cases (full frame, chunked oracle, nested, sequential) use only text columns, because the chunked oracle declines numeric, gen and `chapter_preserve` shapes |
| Non-blocking: M2 and M3 fixtures | M2 uses two rows with equal string forms and distinct original types (`1` and `"1"`) on a per-value failure. M3 uses two handler calls in one process with different namespaces and corpora |
| Non-blocking: AT-1 parity passes on base | Stated. AT-2 call counts, AT-4 and AT-6 give the fail-before |
| Non-blocking: attainable fatal-precedence fixture for AT-2 | AT-2 uses a chapter corpus with an absent-chapter row, then a valid draw, under a lone-surrogate namespace |
| Non-blocking: nonempty out-of-core output can be `large_string` under `future.infer_string=True` while out-of-core declares `string` | Added to V2-LOG (existing behavior) |
| Non-blocking: AT-3 placement in `test_ooc_code_set_arrow.py` | Passed to the S2 re-plan |

Title changed to drop the out-of-core clause.

## Changes in revision 5

Revisions 1 to 4 tried to build a new native operator, an Arrow front for the handler and a hoisted, boxed key in one row. Three review rounds kept finding the same class of defect: a native or Arrow route reads the physical Arrow value, while the oracle reads the value pandas reconstructs, and the two can differ in key text, output width and payload size. Revision 5 fixed this at the root by not creating a second interpretation. The handler routes keep the oracle's own loop and add a per-distinct memo. Native routes, the hoisted key and the Arrow front moved to V2-LOG (section 13). Codex r2 findings 5 and 6 (`verify_corpus` projection and customer-file stats) are existing main behavior and went to candidate row CODE-SET-CORPUS-TEXT-HYGIENE in vault `OWNER-QUESTIONS.md`. Rev 5 removed the census rehome, the draw-catalogue re-pin, the operator snapshot and all size moves. This row changes no sentry baseline, census, catalogue digest or size ceiling.

## 1. Frame

`code_set` remaps a code (ICD-10, MCC) to another real code from a pinned corpus. In mask mode the output is a pure function of `str(value)`, the config, the mask key, the namespace and the pinned corpus record (`transforms/code_set.py:262`, `_pick_mask` at `:465`, chapter path `_apply_chapter_preserve`). `row_index` is read only in gen mode.

Today the handler (`execution/_strategies/_code_set.py`, loop at about `:202-239`) calls `apply_code_set(str(value), ...)` once for every non-missing row. Each call re-runs `derive` (HKDF plus HMAC) and the selection. Dell estimate from the earlier microbenchmark: 21 to 23 us per row on the shipped `icd10` corpus. Code columns repeat heavily (a few thousand distinct codes over millions of rows), so most of that work is repeated. The handler serves four routes: pandas full frame, the chunked oracle leg, nested `_nested_leaves` and sequential non-key columns.

Separate problem, not fixed here: out-of-core reads the physical Arrow value and can mask the same input to a different code than the full frame (int64 `[1, null, 2]` gives `[R10.9, None, M17.11]` out-of-core and `[L89.90, None, I10]` full frame, with shipped ICD-10, namespace `cs` and key `bytes([17]) * 8`). That is S2, which goes to re-plan (section 12).

## 2. Established solutions

Search run: the earlier revisions surveyed Arrow compute, DuckDB, Polars and Parquet for per-distinct evaluation, and NIST SP 800-188 for keyed pseudonymization. Rev 5 and 6 adopt the simplest of those patterns.

- Compute a pure function once per distinct value and expand: Arrow `dictionary_encode`, Parquet dictionary pages, DuckDB dictionary vectors, Polars categorical `map`. In Python the standard form is memoization keyed by the function's exact input. The handler's exact input is `str(value)`, so the memo key is `str(value)`, not the raw object (`1`, `1.0` and `True` hash equal as Python objects but have different string forms).
- Bounded memoization: `functools.lru_cache(maxsize=...)` bounds entries; caches that hold variable-size values also bound total bytes (for example `cachetools` with a `getsizeof` weight). Rev 6 uses the simpler of the two policies that fit a single pass: stop inserting once full, no eviction. Eviction would add ordering state and gives little for a single row-order pass.
- Keyed pseudonymization by HMAC over a fixed domain (NIST SP 800-188; DE-02). The selection formula does not change.

Custom code left: two dicts, two counters and a cap check in the handler loop. A library cache adds a dependency and per-hit overhead for no gain at this size.

### Reuse inventory

- `apply_code_set` and everything under it: unchanged, called by the memo.
- `CodeSetHandler.run`: same loop, record pin, row errors, evidence and assignment.

## 3. Guarantee and non-goals

After this row:

1. In mask mode, on every handler route, `apply_code_set` is never called for a missing cell, and is called in row order. For a `str(value)` that was stored in the memo, it is called once per handler call. A value whose first occurrence came after the memo reached a cap is called once per occurrence, as today. Output values, row errors (index, column, trigger, reason, order), failed original objects, the raised exception for fatal cases, evidence and the pandas dtype equal the base handler's, under and over the caps.
2. The memo's retained key bytes never pass `_MEMO_MAX_KEY_BYTES` and its entries never pass `_MEMO_MAX_ENTRIES`. Extra memory over the base loop is bounded by those caps, whatever the column holds.

Non-goals (V2-LOG or re-plan, sections 12 and 13): out-of-core admission (S2, re-plan); a native `code_set` operator on the unified slice or chunked step; a hoisted or boxed key; an Arrow front in the handler; a Rust kernel; gen mode (keeps its per-row loop, since `row_index` matters); memo eviction; any change to loader, provenance or error text (candidate row CODE-SET-CORPUS-TEXT-HYGIENE).

## 4. Enumerations

### Exit paths (handler, mask mode)

| # | Condition | Result |
|---|---|---|
| E1 | `source.isna()` marks the cell (`na_mask` at `execution/_strategies/_code_set.py:203`) | append `None`, no call, no memo entry (as today) |
| E2 | `str(value)` in `done` | append the memoized output, set `masked_any` |
| E3 | `str(value)` in `failed` | append this row's own original object, emit a `RowError` for this row with the memoized reason |
| E4 | not in the memo, `apply_code_set` returns | store in `done` if under both caps, append, set `masked_any` |
| E5 | not in the memo, `PlanCompileError` with a code in `_PER_VALUE_CODE_SET_ERRORS` | build the reason; store it in `failed` if under both caps; append the original object; emit the `RowError` |
| E6 | not in the memo, any other exception (re-raise at `execution/_strategies/_code_set.py:222`) (E4 single-row corpus, pin mismatch, lone-surrogate namespace, ...) | propagates unchanged, at the same row as today, because every earlier row had a non-fatal string form |
| E7 | zero rows, or every cell missing | zero calls; existing assignment branches |
| E8 | an insert would pass `_MEMO_MAX_ENTRIES` or `_MEMO_MAX_KEY_BYTES` | no insert, the memo is closed for the rest of the call; this row and later new values follow E4 or E5 without storing; E2 and E3 still apply to stored values |

### Routes

| Route | After |
|---|---|
| pandas full frame | memoized handler |
| chunked oracle leg | memoized handler per chunk; memo and caps reset per call |
| nested `_nested_leaves` | memoized handler |
| sequential non-key column | memoized handler |
| out-of-core | unchanged in this revision (S2 re-plan) |
| unified slice, chunked native | not admitted today; unchanged (V2-LOG) |

### Codes

No new reason code. No message changes.

### FK shapes and `when:`

- code_set on a non-key payload column of an FK-bearing table: handler output per value is unchanged, so codes stay equal across rows, chunks and runs.
- code_set on a key column: not a separate path in the handler; the same per-value output applies, and FK key handling outside the handler is untouched.
- `when:`-gated code_set columns keep today's `run_with_when_gate` path; the memo lives inside `run`, so the gated subset gets its own memo.

### Fields

- Memo key: `str(value)`, the first argument `apply_code_set` receives today (`transforms/code_set.py:262`).
- Stored success: the returned code. Stored failure: the reason text built at `execution/_strategies/_code_set.py:233`.
- Counters: one shared entry count (`len(done) + len(failed)`) and `memo_bytes` (sum of `sys.getsizeof(key)` for stored keys).

### Output surfaces

| Surface | Change |
|---|---|
| masked column, row_errors, raised errors, evidence | none |
| `docs/execution-backends.md` code_set rows | say "once per distinct value, up to a memory cap" for handler routes |
| CHANGELOG | one line for the speed-up |

## 5. Design

Design notes: no new module, class, abstraction or route. Principle in play: memoization of a pure function with a bounded store (section 2).

### 5.1 Bounded handler memo

In `CodeSetHandler.run`, mask mode only, keep the loop `for i, value in enumerate(source)` and the `na_mask` check.

Module constants in `execution/_strategies/_code_set.py`:

- `_MEMO_MAX_ENTRIES = 65_536`
- `_MEMO_MAX_KEY_BYTES = 8 * 1024 * 1024`

Each has a one-line comment that says why it exists (bound extra memory on high-cardinality, long-string columns). Tests change them with `monkeypatch.setattr` on the module, so the loop reads them at call time, not through default arguments.

Locals for one `run` call: `done: dict[str, str]`, `failed: dict[str, str]`, `memo_bytes = 0`, `memo_open = True`.

Per non-missing cell:

1. `key = str(value)`.
2. If `key in done`: append `done[key]`, set `masked_any`, continue.
3. If `key in failed`: `reason = failed[key]`. Otherwise run today's `try` block unchanged with `key` as the first argument. On success: store if open (step 5), append, set `masked_any`, continue. On a `PlanCompileError` with a code not in `_PER_VALUE_CODE_SET_ERRORS`: re-raise, as today. On a per-value code: `reason = f"code_set could not mask this value ({exc.code})"` (verbatim), store it in `failed` if open (step 5).
4. One row-error site for both the memo hit and the fresh failure: append `RowError(column=column, row_index=i, trigger="mask_error", reason=reason)` and append `value` (this row's own object).
5. Store rule: `size = sys.getsizeof(key)`. If `memo_open` and `len(done) + len(failed) < _MEMO_MAX_ENTRIES` and `memo_bytes + size <= _MEMO_MAX_KEY_BYTES`, insert and add `size` to `memo_bytes`. Otherwise set `memo_open = False` and do not insert. Once closed, the memo stays closed for this call, so the check is one boolean test per later new value.

The memo stores only keys and the values `apply_code_set` returned or the reason text. Outputs are corpus codes and reasons are short fixed text, so the entry cap bounds them. Keys are the variable-size part, so the byte cap counts keys. Both dicts share one entry count and one byte counter.

The two `exc.code` reads and the reason f-string stay inside `run` (F29 inventory keys are file, function and expression; expected delta zero). Gen mode keeps the current loop untouched. The dicts are locals of one `run` call, so no state outlives the column. They hold string forms and output codes, never key material, so the secret-material census is unaffected.

Cost model: `rows x (iteration + isna + str + dict lookup, about 0.3 us) + stored distinct x (today's 21 us) + occurrences of unstored values x 21 us`. With the default caps, a column of short codes stores up to 65,536 distinct values, which covers every shipped corpus.

Cap sizing: 8 MiB is below the 24 MiB headroom in Codex's reproduction, and at 4 KiB per key it stores about 2,000 keys before closing. A short code key (`sys.getsizeof` about 50 to 60 bytes) reaches the entry cap first at about 3.5 to 4 MiB.

## 6. Placement, size and pinned surfaces

No new file. Public names added: none. Private names added: `_MEMO_MAX_ENTRIES`, `_MEMO_MAX_KEY_BYTES`.

| File | Lines now | Ceiling | Change |
|---|---|---|---|
| `execution/_strategies/_code_set.py` | 283 | 600 | memo, caps and one row-error site in the mask loop, about +35 |
| `docs/execution-backends.md`, `CHANGELOG` | - | - | wording |

Tests go in `tests/unit/execution/test_code_set_strategy.py` or a new sibling `tests/unit/execution/test_code_set_memo.py` if the strategy file would pass 600 lines (AT-1, AT-2, AT-5, AT-6), and a new `tests/perf/test_code_set_memo_perf.py` (AT-4).

Pinned surfaces: secret-material census, draw-site catalogue, F29 reason inventory, reason registry, module size, package fan-out and operator snapshot all have zero planned delta. A builder who sees a nonzero delta in any of them stops and reports. No baseline, census or allowlist refresh is part of this plan.

## 7. Defect classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | memoized `RowError` reasons | the memo stores the existing code-only reason string; no new message. Existing value-bearing loader and E4 text is out of scope (candidate row CODE-SET-CORPUS-TEXT-HYGIENE) | AT-1 (reason equality) | M2 |
| 2 | Cleanup missing on an exit path | none added: the memo is two local dicts and two counters | no handle, file or key parameter; locals are freed on every exit, including a raise | n/a | n/a |
| 3 | State and concurrency | memo dicts and counters | locals of one `run` call; caps are read-only module constants | AT-1 (two calls, two namespaces, two corpora) | M3 |
| 4 | Route parity and silent fallback | four handler routes; the scalar fallback past a cap | every route runs the same loop; the fallback is the base scalar call, so over-cap output is the base output | AT-1, AT-6 | M7, M8 |
| 5 | Referential integrity | code_set payloads on FK-bearing tables | handler output is unchanged per value, so joins across rows and runs keep their codes | AT-1 (repeats split across chunks give equal codes) | M1 |
| 6 | Untrusted producer | customer column contents, including long or many distinct strings | memory added by the memo is capped by named constants; no customer value reaches a message | AT-5 | M8, M9 |
| 7 | Check then use | the cap check against the insert | check and insert happen in the same step with the same `size`; the counter only grows | AT-6 (byte cap at exact boundary) | M9 |
| 8 | Weak tests | value parity passes before the change | call counts (AT-2, AT-6), the perf ratio (AT-4) and the memory bound (AT-5) carry fail-before or mutation kills | AT-2, AT-4, AT-5, AT-6 | M7, M8 |
| 9 | Refactor drift | the handler loop gains a memo and one row-error site | golden outputs captured on the base head, under three pandas option sets; gen loop untouched | AT-1 | M1, M6 |
| 10 | Frozen contract drift | full-frame handler output and error text (section 10) | the memo returns what the scalar call returned for the same key; the fallback is the scalar call; reason f-string kept verbatim | AT-1, AT-6 | M2, M8 |
| 12 | Error precedence | fatal and per-value errors | first occurrence calls the unchanged scalar function in row order | AT-2 | M7 |
| 11 | Unbounded resource growth | memo size on a high-cardinality column | entry and byte caps, then scalar fallback | AT-5, AT-6 | M8, M9 |

Recurring-defect catalog: no new validation grammar, persisted type or scanner. The new caps are not raised caps: they are new limits on an internal cache, and passing them only falls back to today's path. No exception context is added (the memo stores strings). No value text is added to any log or message. Mutations run on the final head of the slice, head recorded.

## 8. Acceptance tests

AT-1 parity passes on the base head by design. AT-2, AT-4, AT-5 and AT-6 carry the fail-before or the mutation kills.

| ID | Test | Fail-before or kill |
|---|---|---|
| AT-1 | Golden parity against the base handler, captured on the S1 base head. Two boundaries. (a) At `CodeSetHandler.run`: one object column with `"1"`, `1`, `1.0`, `True`, `None`, `NaN`, `pd.NA`, a lone-surrogate string, and repeats of each; a float column; Int64 with NA; boolean extension; category; datetime64 with NaT; non-empty all-null; zero rows; shipped `icd10` plus one more shipped corpus; namespaces `cs`, another, and absent; `chapter_preserve` false and true, with an absent chapter and a sole-member bucket interleaved and repeated, plus a missing row and a success. Two handler calls in one process with different namespaces and corpora (M3). Gen mode on the same columns. (b) Route entries (full frame, chunked oracle with two chunks that split repeats, nested, sequential) with text columns only, `chapter_preserve` false, mask mode, since the chunked oracle declines numeric, gen and `chapter_preserve` shapes. Compare outputs, the full `RowError` list (index, column, trigger, reason, order), the original failed object per row, evidence in `ctx.code_set_corpora`, pandas dtype and `pa.Table.from_pandas` schema. Run under default pandas options, `mode.string_storage="pyarrow"` and `future.infer_string=True` | M1, M2, M3, M6 |
| AT-2 | Spy on `apply_code_set` inside the handler, default caps. Mask mode: exactly one call per distinct `str(value)` of non-missing cells, in first-occurrence order; zero calls for zero rows and for all-missing input. A column whose first non-null value triggers E4 raises the same exception class, code and message as base at the same call. Fatal precedence: a chapter corpus under a lone-surrogate namespace, with an absent-chapter row first and a valid draw second, records the same row errors as base before the same raise. A lone-surrogate namespace with all-missing input succeeds with zero calls (as base). Gen mode: one call per non-missing row (unchanged) | one call per row today; M7 |
| AT-4 | `perf` marker: 200,000 rows, 2,000 distinct codes, object column, `CodeSetHandler.run` end to end, mask mode, base loop and memo in the same process on the same sample. Require a ratio of at least 15x (ratio only, as the default gate runs `perf`). The PR records the measured ratio and the Dell numbers | about 1x today; M7 |
| AT-5 | Codex reproduction, default caps: 24,000 distinct strings of 4 KiB each in an object column, mask mode, shipped `icd10`, `chapter_preserve` false. The handler completes and its output equals the base output. Under `tracemalloc`, the peak of the memo run minus the peak of the base run on the same input is at most `_MEMO_MAX_KEY_BYTES` plus 2 MiB slack (dict tables and counters). No process memory limit is set, so the test does not depend on the host | unbounded memo adds about 96 MiB; M8, M9 |
| AT-6 | Equal output under and over the caps, with call counts. Column `[a, b, c, a, b, c, d, d]` with `a` and `c` valid codes, `b` a per-value failure (absent chapter under `chapter_preserve`) and `d` valid, with `a`, `b` and `c` of equal length so their `getsizeof` is equal. (i) Default caps: 4 calls. (ii) `_MEMO_MAX_ENTRIES = 2` by monkeypatch: `a` and `b` stored, the memo closes at `c`; calls are `a, b, c, c, d, d` (6). (iii) `_MEMO_MAX_KEY_BYTES` set to exactly `getsizeof(a) + getsizeof(b)`: same calls as (ii), proving the boundary is inclusive and a failed key counts toward bytes. (iv) Both caps at 0: one call per non-missing row. In every case the output, the `RowError` list and failed objects equal the base handler's | M8 (calls drop to 4 in ii to iv), M9 (iii calls drop) |

Existing code_set tests (pin, swap, mismatch, evidence, quarantine, `when:` preflight) stay green unchanged.

## 9. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M1 | key the memo by the raw object instead of `str(value)` | AT-1 (`1`, `1.0`, `True` collide) |
| M2 | memoize the first failed row's object and reuse it for later rows | AT-1 (`1` and `"1"` both fail with equal string forms; the second row must keep its own `"1"`) |
| M3 | lift the memo to module scope | AT-1 (two calls, different namespaces and corpora) |
| M6 | apply the memo in gen mode | AT-1 gen case |
| M7 | remove the memo hit path (call per row) | AT-2, AT-4 |
| M8 | remove both caps (unbounded memo) | AT-5 (peak), AT-6 (call counts) |
| M9 | drop the byte cap, or stop counting failed keys toward it | AT-5 (peak), AT-6 (iii) |

M4 and M5 belonged to S2 and go to its re-plan.

## 10. Frozen contracts

- The full-frame handler output is the reference and does not change. The memo returns exactly what the scalar call returned for the same key, and the fallback is the scalar call, so output is byte-identical under and over the caps. AT-1 and AT-6 check it.
- Error text is unchanged.

## 11. Pre-mortem

- A builder iterates with `source.tolist()` or `to_numpy()` for speed. String forms can differ from `Series.__iter__` (numpy scalar vs Python scalar boxing). Keep the existing iteration. AT-1's float, Int64, bool, category and datetime columns catch a change.
- A builder binds the caps as default arguments or reads them once at import. AT-6's monkeypatch then has no effect and (ii) to (iv) fail.
- A builder adds eviction to "use the cap better". Out of scope; the stop-inserting rule keeps the loop simple and the output is the same either way.
- A high-cardinality column with long values closes the memo early and runs at today's speed. That is the intended trade.
- `sys.getsizeof` differs by Python build. The AT-5 bound uses the same measure as the code, plus slack for dict overhead, so it holds on every supported version.

## 12. Slices

| Slice | Content | Size | Risk | Gate |
|---|---|---|---|---|
| S1 | Bounded handler memo (5.1), AT-1, AT-2, AT-4, AT-5, AT-6, M1 to M3, M6 to M9. Docs and CHANGELOG line | half a builder-day plus gate | R2 | Codex and Dennis; T1 code_set tests plus F29 and census sentries (expected zero delta) |
| S2 | re-plan | - | - | - |

### S2: re-plan

S2 (out-of-core admits a code_set column only when the full-frame converter proves it is text) is out of this revision. It needs a fresh plan. The re-plan must start from these Codex r3 findings, verified at plan head `8873326ee`:

1. Loader-backed sources. Route selection sees `ctx.caller_sources` only (`_pipeline_context.py:519`), so a job with `source_loader` and `source_loader_schemas` gets an empty proof, and a forced run (loader path at `_pipeline_route_exec.py:294`) refuses a supported text job. The schemas exist in `SourceFacts.schemas` (`pipeline/_routing_facts.py:104`).
2. One proof for every consumer. Capacity (`capacity.py:362`, `:430`), the job estimate (`_job_estimate.py:164`) and transform admission (`_transforms_admission.py:382`) call `out_of_core_admission` without the proof, so capacity and estimates can disagree with execution.
3. Prove on the schema pandas actually sees, before staging. Declared casting runs `pre_mask` before pandas (`_pipeline_full_frame.py:164`) and rebuilds the table, dropping metadata (`declared_casting/_boundary.py:263`), so a raw-schema proof can refuse a valid job. The public out-of-core runner calls `run_staged` before `run_preflight` (`_runner.py:194`, `declared_casting/_stream.py:288`), so staging can start before a refusal.

Also carried to the re-plan from rev 5: the section 1 int64 witness and the Codex r2 `double[pyarrow]` reproduction as acceptance cases; AT-3 placement in `tests/parity/test_ooc_code_set_arrow.py` (238 lines) rather than `test_out_of_core_group_c_parity.py` (825 lines); the `_compat.py` size limit (585 of 600).

Until S2 lands, the route-dependent out-of-core output in section 1 stays as it is on main.

## 13. Owner questions and deferred items

In vault `OWNER-QUESTIONS.md`:

- CS-Q1 (Arrow per distinct vs Rust kernel): superseded. The Python memo keeps byte-identical output; no Rust kernel.
- CS-Q3 (gen mode per row in V1): unchanged, recommended yes.
- CS-Q4 (F29 keys): withdrawn; no F29 delta.
- CS-Q5 (kind default): the native code_set operator moves to 1.x, and code_set is a named exception on the run card. Recommended yes.
- Candidate row CODE-SET-CORPUS-TEXT-HYGIENE under "V1 candidate rows" (Codex r2 findings 5 and 6, plus the rev 4 loader and message items).

V2-LOG:

- Native `code_set` operator on the unified slice and chunked step. Preconditions found in the rev 1 to 4 reviews: prove the pandas interpretation per column and per later manual chunk; match pandas string storage width (`large_string` under `mode.string_storage="pyarrow"` or `future.infer_string`); share distinct selections across bounded chunks and size the mapped output against the 32-bit offset limit; a typed fatal path past unified retry; F29 producer review for any rebuilt `PlanCompileError`; strategy-specific chunked veto tests.
- Hoisted, boxed key per handler call or batch (cuts about 15 us per distinct). Requires lazy derivation on the first draw, plus a census rehome and draw-catalogue re-pin.
- Arrow front for Arrow-backed text Series in the handler.
- Memo eviction (LRU or frequency) for columns that close the memo early.
- Out-of-core admission of null-free integer code columns (with or after the S2 re-plan).
- Out-of-core output type: an all-missing string payload is fixed `string` while the full frame gives Arrow null; a nonempty payload can serialize as `large_string` under `future.infer_string=True` while out-of-core declares `string` (existing).
- Out-of-core `code_set_map` builds one `pa.string()` array per batch; payloads are bounded by `batch_rows` (existing).
- One corpus resolution per run for `when:`-gated and nested code_set: `preflight` resolves and discards, then `run` resolves again (existing).
- Chunked oracle leg: per-chunk pandas metadata is not checked against the first chunk (existing).
- A native code_set tenant on the sequential FK route.
- Merge the two `code_set_corpora` aggregators (`execution/_chunked_code_set.py`, `execution/_chunked_output_sink.py`).
