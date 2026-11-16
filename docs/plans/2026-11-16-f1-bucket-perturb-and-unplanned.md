# F-1 bucket_perturb format errors, and the unplanned V1 rows

Status: plan
Repo: decoy-engine (most slices), with CLI slices named per row. Branch `plan/f1-bucket-perturb-and-unplanned`, cut from engine origin/main `13c95c7de` (#607). CLI read at origin/main `ba7b613e` (#294).
Author: Opus planner, 2026-11-16. Risk tiers per slice: R1 = Codex review only; R2 = Dennis then Codex.
Rules consulted: /home/cam/dev-rules/00-universal.md, /home/cam/dev-rules/risk-and-exceptions.md, /home/cam/dev-rules/development-loop.md, /home/cam/dev-rules/bugfix.md, /home/cam/dev-rules/cross-cutting-concerns.md, /home/cam/dev-rules/catalogs/recurring-defects.md; memory v1-bar-blocking-criteria, v1-scope-no-new-features, plan-defines-acceptance-tests, develop-correctly-registries-and-sizing, best-practice-becomes-a-sentry.

This plan has two parts.

- Part A plans finding F-1: `bucket_perturb` leaves unparseable date cells in clear text and records no row error. This is a leak in an existing feature, so it is a V1 fix (v1-bar: non-admin leak). Risk R2 (value leak, data handling).
- Part B lists every CLI and engine row in ROADMAP section 5 that is not closed and has no plan. It plans the three rows that hold QA groups (17 WF-R, 24b QA-GATE, 24s GEN-CATALOG) and gives one line for each other row.

Not in scope: engine `plan/prop-batch` (docs/plans/2026-11-16-prop-batch.md, slice E-F0) fixes `date_shift` and `fpe` spans inside `text_mask`. This plan does not touch `text_mask` and cites E-F0 as the owner of that part of the class.

Guarantee (F-1): after F1a to F1c, no route writes a non-null bucket_perturb source cell that did not parse under the column's date format; each such cell is a `format_error` row error, handled by the D8 rule. Non-goals: better format detection, `text_mask` spans (E-F0), changing the Rust kernel ABI, new quarantine triggers.

## 1. F-1 verdict

CONFIRMED on engine `13c95c7de`, and wider than reported.

- `transforms/bucket_perturb.py:24` says "Null and unparseable values are passed through unchanged".
- With no `date_format` and no detected format, `transforms/bucket_perturb.py:170` returns `series.copy()`: the whole column passes through in clear text, with only a log warning.
- With a format, `transforms/bucket_perturb.py:172` parses with `errors="coerce"` and `transforms/bucket_perturb.py:181` keeps each unparseable cell (`continue  # preserve null / unparseable values`).
- The handler `execution/_strategies/_bucket_perturb.py:121` and `:141` return `df, []` and `result, []`. It never writes `ctx.row_errors`.
- The precedent `execution/_strategies/_date_shift.py:239` appends a `RowError(trigger="format_error")` for each unparseable cell, and `:227` rebases positions past preserved rows.
- `execution/native/_capabilities.py:211` declares `bucket_perturb` with no `row_error_modes`; date_shift, bucketize and top_code declare `("format_error",)`.
- `execution/_operator_registry.py:227` (bucket_perturb) has no `routed_diagnostics`; date_shift at `:257` has `{"reduce_row_error:format_error"}`.

Every route that runs bucket_perturb leaks the same way (section 4.2). The result is a masked file with real dates in it and no record, on the default config. Under D8 a row error with no quarantine fails the run, so after the fix the default is fail-closed.

Root cause: the kernels return only an output series, so the fact "this cell did not parse" is lost before any caller can act on it. Each caller would have to recompute it, and none does.

### 1.1 Class survey: "unparseable input passes through"

| Strategy | Unparseable or unmatched non-null input | Verdict |
|---|---|---|
| bucket_perturb | passes through, no record | F-1, this plan |
| date_shift | `format_error` row error | correct (precedent) |
| bucketize, top_code, code_set | `format_error` row error | correct |
| nested | propagates child row errors | correct |
| windowed_date | bad anchor raises | correct (fails closed) |
| fpe | failure kills the run | correct (fails closed) |
| geo_generalize | bad lat_lng is suppressed; a short zip such as `"12"` keeps only its digits and can equal the source | probe in sentry S1; allowlist only if the output never equals a non-empty source |
| text_mask date and fpe spans | span passes through | owned by prop-batch E-F0, not here |
| text_redact non-match, shuffle, passthrough | output equals input by design | allowlist with reason |

bucket_perturb is the only handler-level member of the class that is left. The class recurs (date_shift spans, fpe spans, now bucket_perturb), so it gets a sentry (S1), not only a patch.

## 2. Established solutions

Search run: in-codebase first (`git grep` over engine origin/main for `format_error`, `row_errors`, `errors="coerce"`, `FORMAT_ERROR_REASON`), then the reject-row patterns of established data tools from known documentation: Spark's `badRecordsPath` and `mode=FAILFAST|PERMISSIVE`, and the reject file of ETL tools. No web search was run: the engine already has a reviewed, shipped implementation of this exact pattern (date_shift's `format_error` row errors plus the D8 quarantine rule), which is itself the reject-row pattern (fail fast by default, route bad rows to a side output on opt-in).

Design follows: `execution/_strategies/_date_shift.py` (handler) and `native/_date_shift_ext.py` (`native_date_shift` returning `(out, positions)`). Custom code is only the bucket_perturb call sites and one reason lookup.

## 3. F-1 design

The fix mirrors date_shift and is made by construction: the kernels return positions, so a caller cannot drop them without a visible unpack.

1. `apply_bucket_perturb(...)` returns `BucketPerturbResult(series, format_error_positions)`, a NamedTuple. `format_error_positions` is an int64 array of the non-null rows that do not parse.
2. When no format is given and none is detected, every non-null cell is a format error. The output keeps the original text at those rows (trap T4: the pipeline rule drops the row), the same as a per-cell error. A run with no quarantine fails with `RowErrorsFailedError` (D8). The old warning log is removed. Owner Q2.
3. One reason registry: `execution/_row_errors.py` gets `format_error_reason(strategy) -> str` backed by a closed dict (`date_shift`, `bucket_perturb`); an unknown strategy raises. The three hard-coded copies of the date_shift reason (`execution/_sequential_native_ops.py:491`, `execution/native/_chunked_row_errors.py:32`, `execution/physical/_shadow_operators.py:429`) read from it. `native/_date_shift_ext.py:68` `FORMAT_ERROR_REASON` stays as an alias for one release. The bucket_perturb reason is `"value is not a parseable date under bucket_perturb"` (value-free, trap T3).
4. The handler appends one `RowError(column, row_index, "format_error", reason)` per position. With `preserve` set, positions are rebased to the full frame. A new `apply_excluding_preserved_with_errors` in `transforms/date_preserve.py` returns `(series, preserved_count, positions_in_full_frame)`, so the rebase is written once.
5. `native_bucket_perturb(...)` returns `(out, format_error_positions)` like `native_date_shift`. The preserved path rebases through `selected`. Every caller is updated in the same slice:
   - the sequential seam `SequentialNative.bucket_column` (`execution/_sequential_native.py:370`) extends `ctx.row_errors` the way `date_shift_column` does at `:553`;
   - `run_kernel_step` (`execution/native/_operator_step.py:458` and `:471`) returns the positions in `StepResult`;
   - the chunked native route (`execution/native/_chunk_masking.py:275`) carries them in `format_errors`. The assert at `:278` that names date_shift becomes strategy-neutral, and `format_errors` carries the strategy so `format_error_records` picks the right reason;
   - the unified shadow route (`execution/physical/_shadow_operators.py:425`) builds the RowErrors. The "needs a target column" guard at `:288` now covers every operator that can emit positions.
6. Registries: `_capabilities.py:211` gains `row_error_modes=("format_error",)`, and the operator spec at `_operator_registry.py:227` gains `routed_diagnostics={"reduce_row_error:format_error"}`. The `config/_validators.py` QuarantineConfig docstring lists bucket_perturb as a format_error producer. The hand list in `tests/native/test_capabilities.py` ("exactly the five emitters") is replaced by S2, derived from a run.
7. Out-of-core has no quarantine channel.
   - The Python leg (`execution/out_of_core/_mask_group_c.py:495` and `:506`) and the native leg (`out_of_core/_bucket_native.py`) raise `RowErrorsFailedError` with a chunk summary on the first chunk that has a format error, before publish. Row indexes are global (chunk offset plus local position). Raise after the `except` block closes (recurring defect 3).
   - When `quarantine.triggers` covers `format_error`, `_compat.py` sends bucket_perturb to the resident route with a new route reason, as date_shift is in `_DEFERRED_GROUP_B` (`out_of_core/_compat.py:77`). Owner Q1.
8. CHANGELOG: a pre-GA behaviour change. A bucket_perturb job with an unparseable date now fails unless quarantine covers `format_error`.

### 3.1 Design notes

- Choke point: the kernel return type. Every caller must unpack positions; a caller that ignores them is visible in review and caught by the route parity tests and S1. Guard: S1 walks `SCALAR_HANDLERS` (the real registry, not a hand list). Mutation: drop the `ctx.row_errors.extend` in the bucket_perturb handler; S1 goes red.
- Parallel tables: `_capabilities` `row_error_modes`, `_operator_registry` `routed_diagnostics` and the format-error reason table must agree. S2 derives the emitter set from S1's run and checks both registries against it.
- No new structure: one function (`format_error_reason`) in the module that owns `RowError`; one helper variant in `date_preserve.py`. No new module, no new directory.

## 4. Enumerations

### 4.1 Exit paths

- Clean column: output equals today's output byte for byte (the determinism goldens hold).
- Some cells unparseable, no quarantine: `RowErrorsFailedError` (D8), nothing written. The CLI exit is the one it already uses for date_shift row errors.
- Some cells unparseable, quarantine covers `format_error`: those rows go to quarantine, the rest are masked, and the summary counts them under `format_error`.
- No format detected, non-null cells present: every non-null row is a format error, then one of the two cases above.
- All-null column: returns a copy, no errors (unchanged).
- Out-of-core with any unparseable cell: `RowErrorsFailedError`, nothing published (the existing publish-unit cleanup removes staging).

### 4.2 Routes

Every route that runs bucket_perturb, with the file that must handle positions:

- Pandas oracle, full frame: `execution/_strategies/_bucket_perturb.py:137` (handler) calls `apply_bucket_perturb`.
- Sequential Python leg and nested child: the same handler.
- Chunked oracle: the handler per chunk; `execution/_chunked_oracle.py:486` already raises `RowErrorsFailedError` on any chunk row error.
- Sequential native seam: `execution/_sequential_native.py:370` `bucket_column`, through `_sequential_native_ops._bucket_apply` to `native_bucket_perturb`.
- Chunked native: `execution/native/_operator_step.py:458` from `_chunk_masking.py`; admission in `execution/_chunked_bucket_perturb.py` (string sources only).
- Unified physical shadow: `execution/physical/_shadow_operators.py:425`.
- Out-of-core Python: `execution/out_of_core/_mask_group_c.py:435`.
- Out-of-core native: `execution/out_of_core/_bucket_native.py` `native_bucket_perturb_array`.

### 4.3 FK shapes

- bucket_perturb on a PK or FK column: chunked admission refuses it (`execution/_chunked_bucket_perturb.py:298`, `CHUNKED_BUCKET_PERTURB_FK_KEY_UNSUPPORTED`).
- A bad date in a perturbed non-key column of a parent table, resident route, quarantine on: the quarantined parent row leaves the output, and the existing quarantine FK cascade removes its children. Test A14.
- N/A for any new FK behaviour beyond these: bucket_perturb never rewrites key values, and quarantine owns the cascade.

### 4.4 Fields

- `RowError.column`, `row_index` (frame-global, rebased past preserved rows and chunk offsets), `trigger="format_error"`, `reason` from `format_error_reason("bucket_perturb")`.
- `StepResult.format_error_positions` (already exists for date_shift).
- `_Ortho.row_error_modes` and `OperatorSpec.routed_diagnostics` for bucket_perturb.

### 4.5 Output surfaces

- The masked output: no unparseable source text in a written row on any route.
- The quarantine file: holds the bad rows (the original value is allowed there, as for date_shift).
- The run summary and `--json`: `format_error` count; reason text value-free.
- Logs: the removed warning; no new log carries a value (log-hygiene rule).
- Evidence manifest: the row-error summary block, unchanged shape.

## 5. Acceptance tests, red first

Each test fails on `13c95c7de` and passes after its slice. Builders write these first and record them red.

| Id | Test | Fails before because | Slice |
|---|---|---|---|
| A1 | Handler: `["2020-01-05", "not a date", None]`, explicit format, no quarantine: `run_pipeline` raises `RowErrorsFailedError` with one record, row 1, `format_error` | the run succeeds and row 1 is `"not a date"` in the output | F1a |
| A2 | Same with quarantine `triggers: [format_error]`: output has rows 0 and 2, quarantine has row 1, summary counts 1 | no quarantine row | F1a |
| A3 | No format detectable (`["abc", "def"]`): raises with 2 records; an all-null column returns a copy with no records | the whole column passes through | F1a |
| A4 | `preserve` set: a bad row after a preserved row reports its full-frame index | no positions | F1a |
| A5 | Chunked oracle, bad cell in chunk 2: `RowErrorsFailedError` with the global row index | silent | F1a |
| A6 | Out-of-core Python leg with explicit `date_format`, one bad cell: raises, no published file, no staging dir | silent | F1a |
| A7 | Reason registry: records from both strategies carry their own reason; no reason contains the cell text; the date_shift reason literal appears only in the registry (grep sentry) | reason hard-coded to date_shift in three files | F1a |
| A8 | Parity: pandas leg and sequential native leg on the same frame raise the same records | native leg silent | F1b |
| A9 | Chunked native leg (string source) raises the same records as the chunked oracle | silent | F1b |
| A10 | Unified shadow route: same records as the oracle; the column guard fires for bucket_perturb with no target column | silent; guard covers date_shift only | F1b |
| A11 | Capabilities and operator registry declare `format_error` for bucket_perturb; the unified route does not decline it for unrouted obligations | undeclared | F1b |
| A12 | Out-of-core native leg: raises with global row indexes, nothing published | silent | F1c |
| A13 | Out-of-core with quarantine covering `format_error`: route is resident, with the new route reason in `--explain` | admitted today | F1c |
| A14 | FK cascade: parent row with a bad date quarantined, its children leave the output | parent kept with real date | F1a |
| S1 | Sentry: for each strategy in `SCALAR_HANDLERS`, an adversarial non-null cell gives an output that differs from the source, or a RowError, or a raise, or an allowlist entry with a written reason. A strategy with no case and no allowlist entry fails | bucket_perturb fails it | F1a |
| S2 | Sentry: the set of strategies whose handler appended a RowError in S1 equals the set declared in `_capabilities` `row_error_modes` and in `_operator_registry` `routed_diagnostics` | bucket_perturb undeclared | F1b |

Seeded-bypass proof for S1 (cross-cutting rule): in a scratch copy, register a test strategy that returns its input; S1 must go red. Record it.

Existing tests that use unparseable bucket_perturb fixtures (about 30 files, among them `tests/unit/execution/test_bucket_perturb.py`, `tests/physical/test_shadow_bucket_perturb.py`, `tests/native/test_chunked_bucket_perturb_parity.py`, `tests/parity/test_phase_d_d1b1_bucket_*.py`) change in two ways only: kernel callers unpack the new tuple, and route tests that asserted passthrough now assert the same `RowErrorsFailedError` on both legs. The gate diff-checks every test edit for weakened assertions (memory builders-route-around-divergence).

## 6. Reuse inventory

- `RowError`, `drain_row_errors`, `RowErrorsFailedError`, the D8 quarantine rule: reused as-is.
- `native_date_shift` return shape and the `run_kernel_step_masked` rebase through `selected`: the pattern for `native_bucket_perturb`.
- `date_shift_row_errors` (`_sequential_native_ops.py`): generalized to take the strategy, not copied.
- `format_error_records` (`native/_chunked_row_errors.py`): reused with the strategy key.
- `_DEFERRED_GROUP_B` pattern in `out_of_core/_compat.py`: reused for the quarantine reroute.
- `chunk_row_error_summary`: reused for the out-of-core raise.
- `SCALAR_HANDLERS` (`execution/_strategies/__init__.py:48`): the sentry's source list.

## 7. Defect classes

| Class | Name | Closing structure | Sentry or property test | Mutation that must go red |
|---|---|---|---|---|
| 1 | value leak (unparseable value kept in clear text) | kernels return positions; handler and every native caller turn them into RowErrors | S1 no-silent-passthrough sentry over `SCALAR_HANDLERS`; A1 to A13 | drop the `ctx.row_errors.extend` in the handler; S1 and A1 go red |
| 2 | cleanup on failure | out-of-core raise happens before publish; publish-unit staging cleanup reused | A6, A12 assert no published file and no staging dir | move the raise after publish; A6 goes red |
| 3 | state across chunks | positions are chunk-local, rebased with the chunk offset in one helper | A5, A9, A12 assert global indexes | drop the offset; A5 goes red |
| 4 | route divergence | one return shape for both kernels; parity tests per route | A8 to A10 parity | revert the shadow builder to date_shift only; A10 goes red |
| 5 | referential integrity | quarantine FK cascade reused | A14 | skip the cascade for format_error; A14 goes red |
| 6 | untrusted input | the bad cell is untrusted text; it never reaches a reason, log or exception context | A7 value-free reason check; `__context__ is None` on the raise | put the value in the reason; A7 goes red |
| 7 | TOCTOU / check-then-use | N/A: there is no separate check step; the kernel reports what it parsed in the same pass |  |  |
| 8 | weak tests | route tests flipped to assert equal errors on both legs, never deleted | gate diff-check of test edits | change a test to `pytest.raises(Exception)`; the gate rejects it |
| 9 | refactor drift (reason string copies) | one `format_error_reason` registry | A7 grep sentry: the date_shift reason literal only in the registry | re-add a literal copy; A7 goes red |
| 10 | frozen contract change | `RowErrorRecord` shape unchanged; `FORMAT_ERROR_REASON` kept as alias; behaviour change in CHANGELOG | compatibility contract tests unchanged and green | remove the alias; the import test goes red |

## 8. Frozen contracts

- `RowErrorRecord` and the row-error summary shape: unchanged.
- `apply_bucket_perturb` and `native_bucket_perturb` are internal (not in `decoy_engine.__all__`); their return type changes. Check the frozen-surface map (engine #599) before merge; if either is listed, the slice carries a FROZEN note.
- `native/_date_shift_ext.FORMAT_ERROR_REASON` stays importable for one release.
- The behaviour change (pass to fail on bad dates) is pre-GA and goes in CHANGELOG.

## 9. Slices

| Slice | Repo | Risk | Production files (max 10, 800 lines) | Tests |
|---|---|---|---|---|
| F1a pandas, reasons, out-of-core Python | engine | R2 | `transforms/bucket_perturb.py`, `transforms/date_preserve.py`, `execution/_strategies/_bucket_perturb.py`, `execution/_row_errors.py`, `execution/native/_date_shift_ext.py`, `execution/out_of_core/_mask_group_c.py`, `config/_validators.py` (docs), CHANGELOG | A1 to A7, A14, S1, kernel-caller unpacking |
| F1b native routes | engine | R2 | `execution/native/_bucket_perturb_ext.py`, `execution/_sequential_native.py`, `execution/_sequential_native_ops.py`, `execution/native/_operator_step.py`, `execution/native/_chunk_masking.py`, `execution/native/_chunked_row_errors.py`, `execution/physical/_shadow_operators.py`, `execution/_operator_registry.py`, `execution/native/_capabilities.py` | A8 to A11, S2 |
| F1c out-of-core native and reroute | engine | R2 | `execution/out_of_core/_bucket_native.py`, `execution/out_of_core/_compat.py`, one `reasons/route/` catalog file (one new code), the reason manifest | A12, A13 |

Expected size: F1a about 250 lines of source, F1b about 300, F1c about 120, plus tests. No new public names in `decoy_engine.__all__`.

### 9.1 Placement

| New thing | Where | CODEMAP reason | Sits beside |
|---|---|---|---|
| `format_error_reason()` | `execution/_row_errors.py` (existing file) | the module that owns `RowError` | `drain_row_errors` |
| `apply_excluding_preserved_with_errors()` | `transforms/date_preserve.py` (existing file) | preserve helpers live there | `apply_excluding_preserved` |
| new route reason | `reasons/route/` existing part file | route reasons catalog | `_DEFERRED_GROUP_B` codes |

No new file or directory. `_shadow_operators.py` and `_operator_step.py` are on the physical-seam allowlist already; check the edit stays inside it.

### 9.2 Order, release and repin

F1a, then F1b, then F1c, all in one engine release. Between F1a and F1b main still leaks on the native routes as it does today, so no engine tag should carry F1a without F1b and F1c: if the daily train cuts before F1c merges, the train goes out without F1a (revert-free, by merging F1a only when F1b is gate-green, or by holding the tag). Then the CLI repin (row 77 train). The CLI needs no source change: it already maps `RowErrorsFailedError`. One CLI e2e test (bad date: exit code and value-free stderr) goes in with the repin.

## 10. Pre-mortem

- A customer config that ran clean now fails. Expected and wanted (it was shipping real dates). The CHANGELOG line and the error text name quarantine as the way to keep going.
- The no-format case could fail a column that the detector missed but pandas could parse with inference. Treating it as all-error is safe (fail closed). If QA finds real columns hit this, the fix is a better detector, not passthrough.
- A builder makes parity tests green by changing both legs to pass through. Blocked by S1 and the gate diff-check.
- The Rust kernel may not expose unparseable positions. Check before F1b: if it cannot report them, compute them in Python after the call (input non-null, parse failed under the same format), as `native_date_shift` does. Do not change the Rust ABI in this slice.
- The out-of-core reroute changes the route for quarantine configs. A13 pins it, and the route reason shows in `--explain`.
- F1a merged, F1b stalls in review: main has a half-fixed state. Mitigated by the order rule in 9.2.

## 11. Owner questions (F-1)

- Q1. Out-of-core with quarantine covering `format_error`: reroute bucket_perturb to the resident route (as date_shift is), or fail closed? Recommended: reroute, so quarantine works on every route.
- Q2. No format detected: treat every non-null cell as a format error (one channel, quarantine-aware), or raise a config error at run? Recommended: format error.

## 12. Roadmap row for F-1 (ready to paste)

| 24zn | F1-BUCKET-FMT (finding F-1, 2026-11-16): `bucket_perturb` records a `format_error` row error for every unparseable date cell, on every route, as `date_shift` does. An undetected format makes every non-null cell a format error. Out-of-core fails closed, or goes to the resident route when quarantine covers `format_error`. A sentry checks that no mask strategy passes non-null input through silently | engine | PLANNED. Plan: engine `plan/f1-bucket-perturb-and-unplanned` (docs/plans/2026-11-16-f1-bucket-perturb-and-unplanned.md), slices F1a, F1b, F1c | finding F-1 | none |

# Part B. Unplanned rows

Method: every row in ROADMAP section 5 (CLI origin/main) that is not DONE, MERGED or deferred, minus the excluded sets (Windows chain 6 and 89; feat/v1plus-* and V2; remote-owned LIB, GEN-REL, GEN-INHERIT, SCAN-ML CLI, F22, F25, F26), minus rows with a plan branch, a plan file on main, or a plan cited in the row. Plan branches were read with `git ls-remote origin 'refs/heads/plan/*'` on both repos.

Already planned today and excluded: 24e, 24zb, 24zi to 24zl, 30, 31, 32, 32c, 24z, 24za, 24zc, 24ze, release rows 46, 47, 76, 78, 88, 90, 90a, 91, and the fit rows. Planned elsewhere: 3 (ci-e2), 16 and 56 (storm-removal), 24p, 24q, 24zf, 27, 29, 32a, 32b, 61 to 64, 66, 68 to 70, 72, 79, 85.

## B1. Rows planned in full here

### B1.1 Row 17 WF-R (QA check EXIT-07)

Verdict: CLI half DONE at CLI `cfdee4ef` (#146, 2026-11-09). It removed the pointer `decoy-platform/docs/guides/cli-yaml-workflows.md` from `src/decoy/cli/explain.py`; no workflow pointer is left in that file. Engine half NOT DONE: `reasons/platform/_part1.py:72` to `:74` export `WORKFLOW_RESTART_INTERRUPTED`, `WORKFLOW_STEP_FAILED`, `WORKFLOW_STEP_NOT_RUN` as live codes (declared at `reasons/platform/_part1.py:239`, `:244`, `:325`). No engine code uses them; the parked platform uses them in its workflow runner tests and docs.

V1 behaviour: the three codes become tombstones. They move to a new `reasons/platform/_retired.py` in the `reasons/route/_retired.py` pattern, with `deprecated_in` set to the next engine version and `replaced_by=None` (workflows are retired with no replacement; `check_integrity` allows a deprecated entry with no replacement). They stay resolvable, so the parked platform still reads its old records. The pinned reason manifest is regenerated.

Acceptance tests (red first):

- W1: `reasons.find("platform", "workflow_step_failed").deprecated_in` is not None. Fails today: None.
- W2: residual sentry: the three spellings appear only in `reasons/platform/_retired.py` and the manifest. Fails today: they are in `_part1.py`.
- W3 (CLI, after repin): `decoy explain` output and every reason code the CLI can print contain no `workflow_` code (EXIT-07). Passes today for the pointer; added as a guard.

Failure modes: the manifest pin is a frozen surface, so the regenerated manifest is the only diff there; the platform keeps importing the names from `reasons.platform`, so `reasons/platform/__init__.py` re-exports them from `_retired`.

Slice WF-R1: engine, R1, files `reasons/platform/_part1.py`, `reasons/platform/_retired.py` (new, beside `_part1.py`, mirrors `reasons/route/_retired.py`), `reasons/platform/__init__.py`, the manifest. W3 rides the next CLI repin. Then row 17 closes and EXIT-07 can run.

### B1.2 Row 24b QA-GATE (QA checks GATE-05 to GATE-07)

Verdicts per check:

- GATE-06 (`fpe` with no namespace, exit 1 at validate): likely DONE. Engine #569 (`e6eeea105`) added `plan/checks/_required_settings.py`; `contracts/strategy_requirements.py:62` requires a namespace for fpe; `plan/_compile.py:250` calls `check_required_strategy_settings`; `decoy validate` runs the compile layer. Close with acceptance test G6 only.
- GATE-05 (a declared column missing from the source, exit 1 at validate): NOT DONE. CLI #255 (`b272beb8`) checks declared columns before any row on `run`, `api`, `demo` and `subset` through `_sources.prepared_sources`, but the gate preflight layer (`src/decoy/cli/gate/_layers.py:325`) only checks that files exist (`_check_source_files`). So validate exits 0 and run refuses.
- GATE-07 (a DP release with no labels for a sampled column, refused at validate): NOT DONE. The compile check `plan/_checks.py:286` `check_statistical_columns` runs `load_spec`, which does not test for a degenerate sample. The run-time predicate is `generation/_window_admission.py:241` `_check_statistical` with `CODE_DEGENERATE` (`_window_admission.py:42`).

V1 behaviour: validate refuses what run refuses, with the same code and exit 1.

Acceptance tests (red first):

- G5: a config that declares column `email` on a CSV without it: `decoy validate` exits 1 with the code `run` gives; no data row is read (header only). Fails today: exit 0.
- G5b: a headerless CSV whose `column_names` lack a declared column: same. A missing source file stays the existing preflight finding, not a second one.
- G6: `fpe` with no namespace: `decoy validate` exits 1 with `fpe_requires_namespace`. Expected green today; if red, the fix is in the CLI compile layer.
- G7: a generate config whose DP snapshot has an empty label set for a sampled column: `decoy validate` exits 1 with `statistical_stats_degenerate`; `decoy run` gives the same code. Fails today: validate exits 0.
- GATE-08 (row 23) then runs `decoy run` on the same configs and expects the same exit.

Design:

- G-cli (CLI, R2): the preflight layer calls `prepared_sources(validated_config, base_dir=config.parent)` after `_check_source_files` passes, and turns a `PipelineValidationError` into a preflight error finding with its code. One choke point, no second column check. DuckDB sources use the schema path `run` uses (`for_supplied` with `DESCRIBE`), which #255 wires. Files: `src/decoy/cli/gate/_layers.py`, plus `src/decoy/cli/preflight.py` if the finding helper lives there. Tests: G5, G5b, G6.
- G-eng (engine, R2): move the degenerate test out of `_window_admission._check_statistical` into one predicate under `generation/statistical/` and call it from both `_check_statistical` (run) and `check_statistical_columns` (compile). One predicate, two callers, one code. Files: `generation/_window_admission.py`, `plan/_checks.py`, one existing module under `generation/statistical/`. Test: G7 at engine compile level, and in the CLI after repin.

Failure modes: the gate must not read data rows (the header read is the one `run` makes); a config whose source is absent stays a "file not found" finding, not a crash; findings are value-free (declared names only, which are config text).

Release: G-eng goes in the next engine release; after the CLI repin G7 runs end to end. G-cli can merge first (G5, G6 do not need G-eng).

### B1.3 Row 24s GEN-CATALOG (QA check GEN-14)

Verdict: NOT DONE. Pieces exist: `decoy list providers` reads `providers_v2.get_default_registry()` (`src/decoy/cli/cockpit.py:181`); `decoy explain generation` renders `generate_option_catalog()` (`src/decoy/cli/gen/_topic.py:60`); `decoy_engine.list_generate_faker_providers()` exists (`internal/faker_setup.py:608`). There is no list kind for generate types and options, no list of faker types, and one generate template only (`src/decoy/templates/generate.yaml`).

V1 behaviour:

- `decoy list generate-types [--json]`: one row per type from `generate_option_catalog()`, with its options and the common options. No hand list.
- `decoy list faker-types [--json]`: every value from `list_generate_faker_providers()`.
- Six generate starter templates: `generate-healthcare`, `generate-banking`, `generate-insurance`, `generate-retail`, `generate-telecom`, `generate-hr`. Each is a multi-table config with a declared FK and only registered types and faker types. `decoy list templates` and `decoy show template` show them; `decoy init` offers them.

Acceptance tests (red first):

- C1: `decoy list generate-types --json` names exactly the keys of `generate_option_catalog()`. Fails today: unknown kind, exit 1.
- C2: `decoy list faker-types --json` equals `list_generate_faker_providers()`. Fails today.
- C3: each of the six templates passes `decoy validate` and `decoy run` at a small row count, and its output FK links. Fails today: templates absent. `tests/e2e/test_bundled_templates_e2e.py` iterates the registry, not a fixed list.
- C4: guard: every `type` and `faker_type` in every template is in the live catalogs, so a later rename fails here, not at a user's run.
- C5: DOC-08 still holds: a bad kind exits 1 and lists the known kinds.

Slices:

- GC1 (CLI, R1): two list kinds in `src/decoy/cli/reference.py` (`_LIST_READERS`, `_SINGULAR_TO_PLURAL`) and readers in `src/decoy/cli/cockpit.py`. Tests C1, C2, C5. Can land now.
- GC2 (CLI, R1): six YAML files under `src/decoy/templates/`, `_REGISTRY` entries in `src/decoy/templates/__init__.py`, tests C3, C4. Lands after 24q (GEN-TYPES, in progress), so the templates can use the new types where they fit.

Engine: no change. If C4 finds a faker type the catalog does not export, that is a 24p item.

Failure modes: templates use faker output only, no real-looking seeds; the disguise drift test (`tests/unit/test_template_disguise_drift.py`) covers mask templates only, so generate templates carry no `x-derived-from-disguise` marker.

## B2. Rows not planned here, one line each

| Row | QA group held | What it needs |
|---|---|---|
| 18 R-c | groups 1 and 16 (INST-11, BLD-05) | Nothing to build. R-c shipped short of its list and later releases carry the rest. Recommend marking it CLOSED (folded into 77) so it stops holding groups. Owner Q3. |
| 75 One CLI journey | group 15 (DOC-05) | A short plan after CLI delivery (61): write the V1 journey as numbered ids in `docs/`, one e2e test per id, and make `release-smoke.yml` cite the ids. CLI, R1. |
| 64b CLI-DB-SRC | group 6 | A plan after CLI delivery: `type: postgres` source through engine `postgres_snapshot`, the value-free connection reference, and a Postgres CI lane (CI-P2 markers). Engine and CLI, R2. |
| 80 F15 | group 4 | Plan after the STORM rename and SCAN-LIB: bound-baseline object and strict-drift block; scan-diff moves to engine `scan-diff/v1`. |
| 81 F16 | group 4 | Plan after the Phase 1 rows: selector grammar, prohibition predicates, 5-level precedence, disguises in the engine. Large; split before planning. |
| 82 F07 | none | Plan after the STORM rename: bounded path discovery, nested-path relations, JSONB coverage. |
| 83 F13 adapters | KEY-08 | Owner Q4 first: the F13 v1-scope plan puts external adapters in Phase 2. If V1, plan per adapter (Vault, AWS, GCP, Azure). |
| 84 F24 engine half | none | Small plan: add the ingestion peak to the estimator (engine #328); advisory only. |
| 86 F01 | group 6 | Plan after F22 settles: Postgres write target with staging, constraint and index restore, atomic publish, type-mapping report. Owner said CLI V1. |
| 87 F02 | group 6 | Plan after CLI-CLOUD and the F22 adapter: SFTP, cloud scan, subset against cloud, retry executor, content digest. |
| 54 H-1 E7 | none | Per file as blockers merge; the H-1 Wave B plan (platform `plan/h1-wave-b`) is the method. No new plan. |
| 48 to 53 H-1 | BLD-03 (46, 53) | Wave B plan exists (platform `plan/h1-wave-b`, rev 3 handoff); needs handoffs only. |
| 77 Later releases | never holds a group | Covered by the release-chain plan's train; no plan. |
| 92 REL-DOCS | DOC-01, DOC-06, DOC-07 | Plan is decoy-web-docs `DOCS-PLAN.md`; the host waits on REL-WEB Q1. |
| 94 CLI-REL | INST-11, BLD-06 | S0 is in the rel-gate and release-chain plans; the rest is the final release run. |

## B3. Owner questions

- Q1 (F-1). Out-of-core with quarantine covering `format_error`: reroute to resident, or fail closed? Recommended: reroute, as date_shift does.
- Q2 (F-1). No format detected: all non-null cells are format errors, or a run-time config error? Recommended: format errors.
- Q3 (row 18). Mark R-c CLOSED as folded into row 77, so it stops holding QA groups 1 and 16? Recommended: yes.
- Q4 (row 83). Are F13 external secret adapters V1 (row text) or Phase 2 (F13 v1-scope plan)? Recommended: Phase 2; keep the `env:` and file references for V1.
- Q5 (row 24s). Six industry templates as separate YAML files, or one template with an `--industry` option in `decoy init`? Recommended: separate files; `init` already offers every template.

## Slice summary

| Slice | Row | Repo | Risk | Depends on | Release point |
|---|---|---|---|---|---|
| F1a | 24zn (F-1) | engine | R2 | none | same engine tag as F1b, F1c |
| F1b | 24zn | engine | R2 | F1a | same tag |
| F1c | 24zn | engine | R2 | F1b, Q1 | tag, then CLI repin with e2e test |
| WF-R1 | 17 | engine | R1 | none | next engine tag; W3 at repin |
| G-cli | 24b | CLI | R2 | none | CLI main |
| G-eng | 24b | engine | R2 | none | next engine tag; G7 at repin |
| GC1 | 24s | CLI | R1 | none | CLI main |
| GC2 | 24s | CLI | R1 | 24q merged | CLI main |

## Worker rules

- Name the class of each finding (section 7 numbers) before you fix it.
- Write the acceptance tests first and record them red before the fix (fail before, pass after).
- Attack your own diff: mutate each new mechanism once (section 7, last column) and show its test goes red; never commit with a mutation applied; rerun mutations on the final head.
- Run baselines in the same environment as the branch, from `uv.lock`, through `~/bin/vm-run`, never on the devbox.
- Never widen a threshold, loosen an assertion or skip a test to make a route agree; a parity failure is a finding.
- Stop and report if a finding repeats a catalogued class a second time in the same slice.
- Commits: Conventional Commits subject, no body unless it says why, final line `cam`. Tests: T0 per edit, T1 per commit.

## Done when

- F1a, F1b and F1c are merged with A1 to A14, S1 and S2 green, released in one engine version, and the CLI is repinned with its e2e test. Row 24zn is DONE.
- WF-R1 is merged and released; W3 is green after the repin; row 17 is DONE.
- G-cli and G-eng are merged; G5 to G7 are green at validate; row 24b is DONE.
- GC1 and GC2 are merged; C1 to C5 are green; row 24s is DONE.
