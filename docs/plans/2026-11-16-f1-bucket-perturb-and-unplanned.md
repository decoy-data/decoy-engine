# F-1 bucket_perturb format errors, and the unplanned V1 rows

Status: plan
Repo: decoy-engine (most slices), with CLI slices named per row. Branch `plan/f1-bucket-perturb-and-unplanned`, cut from engine origin/main `13c95c7de` (#607). CLI read at origin/main `ba7b613e` (#294).
Author: Opus planner, 2026-11-16. Risk tiers per slice: R1 = Codex review only; R2 = Dennis then Codex.
Rules consulted: /home/cam/dev-rules/00-universal.md, /home/cam/dev-rules/risk-and-exceptions.md, /home/cam/dev-rules/development-loop.md, /home/cam/dev-rules/profiles/local-operations.md, /home/cam/dev-rules/workspace-and-vcs.md, /home/cam/dev-rules/reuse-first.md, /home/cam/dev-rules/exploration.md, /home/cam/dev-rules/scope-discipline.md, /home/cam/dev-rules/proportionality.md, /home/cam/dev-rules/verification.md, /home/cam/dev-rules/code-review.md, /home/cam/dev-rules/testing.md, /home/cam/dev-rules/architecture.md, /home/cam/dev-rules/cross-cutting-concerns.md, /home/cam/dev-rules/bugfix.md, /home/cam/dev-rules/api-and-compatibility.md, /home/cam/dev-rules/observability-and-resilience.md, /home/cam/dev-rules/documentation.md, /home/cam/dev-rules/catalogs/recurring-defects.md; memory v1-bar-blocking-criteria, v1-scope-no-new-features, plan-defines-acceptance-tests, develop-correctly-registries-and-sizing, best-practice-becomes-a-sentry.

This plan has two parts.

- Part A plans finding F-1: `bucket_perturb` leaves unparseable date cells in clear text and records no row error. This is a leak in an existing feature, so it is a V1 fix (v1-bar: non-admin leak). Risk R2 (value leak, data handling).
- Part B lists every CLI and engine row in ROADMAP section 5 that is not closed and has no plan. It plans the three rows that hold QA groups (17 WF-R, 24b QA-GATE, 24s GEN-CATALOG) and gives one line for each other row.

Not in scope: engine `plan/prop-batch` (docs/plans/2026-11-16-prop-batch.md, slice E-F0) fixes `date_shift` and `fpe` spans inside `text_mask`. This plan does not touch `text_mask` and cites E-F0 as the owner of that part of the class.

Guarantee (F-1): after F1b, no route writes a non-null bucket_perturb source cell that did not parse under the column's resolved date format; each such cell is a `format_error` row error, handled by the D8 rule. After F1c, out-of-core configs whose quarantine covers `format_error` take the resident route. Non-goals: changing `date_shift`'s own format detection, `text_mask` spans (E-F0), changing the Rust kernel ABI, new quarantine triggers.

Revision 3 (2026-11-16) resolves Dennis round 2 on `50568d034` (2 HIGH, 4 MEDIUM, 2 LOW). It keeps the round 1 owner answers and the majority-format decision. The finding maps are in sections 13 and 14.

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
| geo_generalize | bad lat_lng is suppressed; a zip shorter than the generalization width (such as `"12"`) keeps only its digits and can equal the source | decided: S1 allowlist entry with reason (the output never carries more than the zip3 prefix Safe Harbor allows) plus its own check G-ZIP: any input with 3 or more digits gives an output that differs from the normalized source |
| text_mask date and fpe spans | span passes through | owned by prop-batch E-F0, not here |
| text_redact non-match, shuffle, passthrough | output equals input by design | allowlist with reason |

bucket_perturb is the only handler-level member of the class that is left. The class recurs (date_shift spans, fpe spans, now bucket_perturb), so it gets a sentry (S1), not only a patch.

## 2. Established solutions

Search run: in-codebase first (`git grep` over engine origin/main for `format_error`, `row_errors`, `errors="coerce"`, `FORMAT_ERROR_REASON`), then the reject-row patterns of established data tools from known documentation: Spark's `badRecordsPath` and `mode=FAILFAST|PERMISSIVE`, and the reject file of ETL tools. No web search was run: the engine already has a reviewed, shipped implementation of this exact pattern (date_shift's `format_error` row errors plus the D8 quarantine rule), which is itself the reject-row pattern (fail fast by default, route bad rows to a side output on opt-in).

Design follows: `execution/_strategies/_date_shift.py` (handler) and `native/_date_shift_ext.py` (`native_date_shift` returning `(out, positions)`). Custom code is only the bucket_perturb call sites and one reason lookup.

## 3. F-1 design

The fix mirrors date_shift and is made by construction: the kernels return positions, so a caller cannot drop them without a visible unpack.

1. `apply_bucket_perturb(...)` returns `BucketPerturbResult(series, format_error_positions)`, a NamedTuple. `format_error_positions` is an int64 array of the non-null rows that do not parse under the resolved format. `native_bucket_perturb(...)` returns `(out, format_error_positions)` like `native_date_shift`; the preserved path rebases through `selected`.
2. Format resolution (owner Q2 decision, review M5). An explicit `date_format` is used as given. Without one, only the resident pandas handler runs a new `_detect_majority_format(series)` in `transforms/bucket_perturb.py`. It takes `dropna().astype(str).head(200)`, strips each string, counts how many values each format in `transforms/date_shift._COMMON_FORMATS` parses, and picks the highest count. Ties go to the earlier format in `_COMMON_FORMATS`. A format that parses no sample value is not a candidate. If no format parses any value, every non-null cell is a format error. The detector sees only the rows passed to the handler and, for `preserve`, only the rows passed to the kernel. `when:` selection occurs before the handler. Preserve filtering occurs before detection. The sequential-native leg declines at `_sequential_native.py:392` and falls through to pandas. Every other non-pandas leg already refuses autodetect at `_chunked_bucket_perturb.py:84`, `out_of_core/_compat.py:427`, `out_of_core/_mask_group_c.py:473`, and `physical/_shadow_bindings.py:364`. The plan does not add a second detector or pass a detected format into those legs. `date_shift._detect_format` is not changed. The old warning log in `transforms/bucket_perturb.py:168` is removed.
3. One reason registry: `execution/_row_errors.py` gets `format_error_reason(strategy) -> str` backed by a closed dict (`date_shift`, `bucket_perturb`); an unknown strategy raises `KeyError`. The four hard-coded copies of the date_shift reason read from it: `execution/_strategies/_date_shift.py:240`, `execution/_sequential_native_ops.py:491`, `execution/native/_chunked_row_errors.py:32`, `execution/physical/_shadow_operators.py:429`. `native/_date_shift_ext.py:68` `FORMAT_ERROR_REASON` stays as an alias for one release. The bucket_perturb reason is `"value is not a parseable date under bucket_perturb"` (value-free, trap T3). 24zb E1 is building now and edits `_strategies/_date_shift.py`; slice F1-0 rebases after it merges.
4. The handler appends one `RowError(column, row_index, "format_error", reason)` per position. With `preserve` set, positions are rebased to the full frame by a new `apply_excluding_preserved_with_errors` in `transforms/date_preserve.py` that returns `(series, preserved_count, positions_in_full_frame)`. A `when:` gate rebases through the existing `_when_gate.py:85` path (pandas) and the `run_kernel_step_masked` rebase through `selected` (native); both are covered by acceptance tests.
5. Native callers are prepared generically in F1-0 and turn errors on together in F1b:
   - F1-0 changes `_sequential_native.py:88` to import the generic `format_error_row_errors` name and changes the call at `:553`. Its net line change stays zero or less, and its 700-line ceiling is not raised. F1-0 also changes `native/_chunked_entry.py:311` to the strategy-generic error carrier type and `:348` to the generic record builder. F1b then supplies bucket_perturb positions to these prepared carriers;
   - the sequential seam: `SequentialNative.bucket_column` (`execution/_sequential_native.py:370`) is taken first by the handler (`_strategies/_bucket_perturb.py:107` to `:121`) whenever the companion is installed, and the FK and sequential route always sets `seq_native` (`execution/_sequential.py:344` to `:351`). The RowErrors are built in `_sequential_native_ops.py` (a strategy-generic `format_error_row_errors(strategy, column, positions)` that replaces `date_shift_row_errors`), and `bucket_column` only extends `ctx.row_errors`. `_sequential_native.py` is at 697 of 700 lines (`tests/sentry/test_module_size.py:130`): its net line change is zero or less (condense in the touched function); the pin is never raised;
   - `run_kernel_step` (`execution/native/_operator_step.py:458` and `:471`) returns the positions in `StepResult`;
   - the chunked native route (`execution/native/_chunk_masking.py:275`) and the unified shadow route (`execution/physical/_shadow_operators.py:425`) are made strategy-generic in F1-0 (they carry any `StepResult` positions with the operator's strategy, and the "needs a target column" guard at `:288` covers every operator whose spec routes `reduce_row_error:format_error`), so F1b needs no edit there;
   - out-of-core native: `out_of_core/_bucket_native.py:271` unpacks the new return in F1a.
6. Registries: `_capabilities.py:211` gains `row_error_modes=("format_error",)`, and the operator spec at `_operator_registry.py:227` gains `routed_diagnostics={"reduce_row_error:format_error"}`. The `config/_validators.py` QuarantineConfig docstring lists bucket_perturb as a format_error producer. The per-trigger pins in `tests/native/test_capabilities.py:102` to `:111` stay and gain bucket_perturb.
7. Row indexes on chunked legs stay chunk-local. That is the existing contract (`execution/native/_chunked_row_errors.py:10` to `:11`): the oracle chunked leg never adds the chunk offset to `row_index` (`_row_errors.drain_row_errors`), and the offset is carried only by the summary from `chunk_row_error_summary` (`execution/_row_error_summary.py:147`, fields `chunk_index` and `chunk_row_offset`; used at `execution/_chunked_oracle.py:486` to `:495`). bucket_perturb follows it on every chunked leg. Slice F1a2 is behavior-neutral. It adds `chunk_index` and `chunk_row_offset` to `out_of_core/_mask.py:369` `mask_batch`, enumerates batches and advances the offset in both `_stream_driver.py:324` and `_rewrite_pass.py:190`, and adds one dormant row-error raise helper inside `mask_batch`. F1b makes the bucket result carry positions and invokes that helper. Both out-of-core drivers then use one raise path and one chunk-summary builder.
8. Out-of-core has no quarantine channel.
   - F1b: `out_of_core/_mask_group_c.py` and `_bucket_native.py` return bucket positions through the existing mask dispatch. The one helper in `out_of_core/_mask.py:369` raises `RowErrorsFailedError` with a `chunk_row_error_summary` on the first bad chunk, before publish. Records are chunk-local. The summary carries the threaded `chunk_index` and `chunk_row_offset`. Raise after the `except` block closes (recurring defect 3). Between F1b and F1c an out-of-core config with quarantine on `format_error` fails closed; that is safe.
   - F1c (owner Q1 answered: reroute): `compile_plan` computes `quarantine_covers_format_error` once from an enabled quarantine block and its triggers. The frozen `Plan` stores this bool. `_serialize.py` writes it and reads a missing field from an older plan as `False`; a present non-bool is refused. The builder follows the current plan-version rule and coordinates any concurrent version bump. `check_out_of_core_compatibility(plan, work, graph, *, source_types=None)` keeps its signature and reads only this Plan fact. It sends bucket_perturb to the resident route with a new route reason, as date_shift is in `_DEFERRED_GROUP_B` (`out_of_core/_compat.py:77`). No caller receives quarantine or a new argument. This covers the capacity caller at `capacity.py:357`, transform admission at `_transforms_admission.py:386`, the job estimate at `_job_estimate.py:142`, routing signals at `_pipeline_routing_signals.py:83`, `:267`, and `:550`, bounded admission at `_pipeline_routing.py:216`, the stream route at `pipeline/_stream.py:214`, physical snapshot and live inputs at `physical/_snapshot.py:197` and `physical/_live_inputs.py:125`, and direct preflight at `out_of_core/_preflight.py:77`. The public `execution.check_out_of_core_compatibility`, root `decoy_engine.estimate_job`, and the platform `api/jobs/estimate_child.py` consumer keep their signatures.
9. Docs (review L1): `transforms/bucket_perturb.py:24` and `:147` docstrings, `docs/qa/07-mask-dates-and-numbers.md:54` to `:55`, `docs/strategies.md` (bucket_perturb entry), CHANGELOG: a pre-GA behaviour change; a bucket_perturb job with an unparseable date now fails unless quarantine covers `format_error`.

### 3.1 Design notes

- Choke point: the kernel return type. Every caller must unpack positions. F1a adds the unpack at every caller and discards positions on purpose with a `# F1b turns these into RowErrors` comment; F1b removes every discard. Guard: S1 walks `SCALAR_HANDLERS` (the real registry, not a hand list). Mutation: drop the `ctx.row_errors.extend` in the bucket_perturb handler; S1 goes red.
- Quarantine-routing choke point: `compile_plan` owns the one `quarantine_covers_format_error` fact, and `check_out_of_core_compatibility` consumes it. Every route, estimate, explain path and public caller already passes the Plan. A13b is the guard. Mutation: ignore the Plan bool in `_compat.py`; every A13b reporting assertion goes red.
- Out-of-core row-error choke point: both batch drivers call `mask_batch`, and only its helper builds and raises the chunk summary. P3 covers both drivers. A6 and A12 cover the Python and native bucket kernels. Mutation: return the failing batch instead of calling the helper; the no-publish assertions go red.
- Parallel tables: `_capabilities` `row_error_modes`, `_operator_registry` `routed_diagnostics` and the format-error reason table must agree. S2 checks them against S1's observed (strategy, trigger) pairs.
- No new structure: two functions (`format_error_reason`, `format_error_row_errors`), one helper variant in `date_preserve.py`, one detection function. No new module except the S1 sentry test file.

## 4. Enumerations

### 4.1 Exit paths

- Clean column: output equals today's output byte for byte (the determinism goldens hold).
- Some cells unparseable, no quarantine: `RowErrorsFailedError` (D8), nothing written. The CLI has no specific mapping for it (no hit in `src/decoy`), so it exits through the generic engine-error path; the repin e2e test pins the exact code (section 9.2).
- Some cells unparseable, quarantine covers `format_error`: those rows go to quarantine, the rest are masked, and the summary counts them under `format_error`.
- No format given, one early bad date, the rest parseable: the majority format is picked and only the bad cell is a format error.
- No format parses any value: every non-null row is a format error.
- All-null column: returns a copy, no errors (unchanged).
- Out-of-core with any unparseable cell: `RowErrorsFailedError` with a chunk summary, nothing published (the existing publish-unit cleanup removes staging). With quarantine on `format_error` (after F1c): resident route.
- Chunk-eligible bucket_perturb with quarantine on: `_chunked_output_sink.py:116` refuses streamed output, so the job finishes on the resident route and quarantines the bad row. Any direct chunked entry that reaches `_chunked_oracle.py:479` still fails closed before yield with `reasons.decoy.ROW_ERRORS_FAILED`. Test A18 pins this disjunction and forbids a successful chunked output that retains the source value.

### 4.2 Routes

Every route that runs bucket_perturb, with the file that must handle positions:

- Pandas oracle, full frame: `execution/_strategies/_bucket_perturb.py:137` (handler) calls `apply_bucket_perturb`.
- Sequential Python leg and nested child: the same handler; the nested strategy propagates child row errors.
- `when:` gated: pandas through `execution/_when_gate.py:85`; native through `run_kernel_step_masked`.
- Chunked oracle: the handler per chunk; `execution/_chunked_oracle.py:486` raises `RowErrorsFailedError` on any chunk row error.
- Sequential native seam: `execution/_sequential_native.py:370` `bucket_column` (taken first by the handler, `_strategies/_bucket_perturb.py:107`), through `_sequential_native_ops._bucket_apply` to `native_bucket_perturb`.
- Chunked native: `execution/native/_operator_step.py:458` from `_chunk_masking.py`; admission in `execution/_chunked_bucket_perturb.py` (string sources only).
- Unified physical shadow: `execution/physical/_shadow_operators.py:425`.
- Out-of-core Python: `execution/out_of_core/_mask_group_c.py:435`.
- Out-of-core native: `execution/out_of_core/_bucket_native.py:271`.

### 4.3 FK shapes

- bucket_perturb on a PK or FK column: chunked admission refuses it (`execution/_chunked_bucket_perturb.py:298`, `CHUNKED_BUCKET_PERTURB_FK_KEY_UNSUPPORTED`).
- A bad date in a perturbed non-key column of a parent table, resident FK route (which sets `seq_native`), quarantine on: the quarantined parent row leaves the output, and the existing quarantine FK cascade removes its children. Test A14 (F1b).
- N/A for any new FK behaviour beyond these: bucket_perturb never rewrites key values, and quarantine owns the cascade.

### 4.4 Fields

- `RowError.column`, `row_index` (frame-global on resident legs, rebased past preserved and `when:`-excluded rows; chunk-local on chunked legs), `trigger="format_error"`, `reason` from `format_error_reason("bucket_perturb")`.
- Chunked summary: `chunk_index`, `chunk_row_offset` (existing fields).
- `StepResult.format_error_positions` (already exists for date_shift).
- `_Ortho.row_error_modes` and `OperatorSpec.routed_diagnostics` for bucket_perturb.

### 4.5 Output surfaces

- The masked output: no unparseable source text in a written row on any route.
- The quarantine file: holds the bad rows (the original value is allowed there, as for date_shift).
- The run summary and `--json`: `format_error` count; reason text value-free.
- Logs: the removed warning; no new log carries a value (log-hygiene rule).
- Evidence manifest: the row-error summary block, unchanged shape.

## 5. Acceptance tests, red first

Each behavior test fails on `13c95c7de` and passes after its slice. F1-0, F1a and F1a2 change no behavior, so P1 to P3 are refactor pins. They pass before and after, and their named mutations show that they can fail. Builders write the F1b and F1c behavior tests first and record them red. Every resident-route test runs twice, with the native companion installed and without it, so both the pandas leg and the sequential native seam are covered.

| Id | Test | Fails before because | Slice |
|---|---|---|---|
| P1 | Reason registry: every date_shift record on every leg carries the registry text; the date_shift reason literal appears only in `_row_errors.py` (grep sentry); an unknown strategy raises | four literal copies | F1-0 |
| P2 | Kernel shape: `apply_bucket_perturb` and `native_bucket_perturb` return positions equal to the non-null rows that fail to parse; every existing output is unchanged | no positions | F1a |
| P3 | Out-of-core context: spies on `mask_batch` show `_stream_driver.py` and `_rewrite_pass.py` pass chunk indexes `0, 1, ...` and cumulative row offsets for uneven batches; output and route evidence stay byte-identical | no chunk context reaches `mask_batch` | F1a2 |
| A1 | Handler: `["2020-01-05", "not a date", None]`, explicit format, no quarantine: raises `RowErrorsFailedError` with one record, row 1, `format_error` | the run succeeds and row 1 is `"not a date"` in the output | F1b |
| A2 | Same with quarantine `triggers: [format_error]`: output has rows 0 and 2, quarantine has row 1, summary counts 1 | no quarantine row | F1b |
| A3a | No format given: 200 ambiguous `01/02/2020` values followed by `31/12/2020`. The head sample ties `%m/%d/%Y` and `%d/%m/%Y`, so declared order wins and only the last row is a format error. With the companion installed, the sequential-native leg records a decline and the resulting records equal a companion-disabled pandas run | today the whole column passes through | F1b |
| A3b | No format given, no value parses (`["abc", "def"]`): two records; an all-null column returns a copy with no records | whole column passes through | F1b |
| A4 | `preserve` set: preserved rows carry a conflicting date format, but detection uses only the rows the handler passes to the kernel; a bad row after a preserved row reports its full-frame index | no positions | F1b |
| A5 | Chunked oracle, bad cell at local row 3 of chunk 2: `RowErrorsFailedError`; the record's `row_index` is 3 (chunk-local); the summary's `chunk_index` is 2 and `chunk_row_offset` equals the rows before chunk 2 | silent | F1b |
| A6 | Out-of-core Python leg with explicit `date_format`, one bad cell: raises with a chunk summary as in A5, no published file, no staging dir | silent | F1b |
| A8 | Parity: pandas leg and sequential native leg on the same frame raise the same records, on the plain and the FK route | native leg silent | F1b |
| A9 | Chunked native leg (string source) raises the same records and summary (`chunk_index`, `chunk_row_offset`) as the chunked oracle | silent | F1b |
| A10 | Unified shadow route: same records as the oracle; the column guard fires for bucket_perturb with no target column | silent; guard covers date_shift only | F1b |
| A11 | Capabilities and operator registry declare `format_error` for bucket_perturb; the unified route does not decline it for unrouted obligations | undeclared | F1b |
| A12 | Out-of-core native leg: raises with chunk-local records and the chunk summary, nothing published | silent | F1b |
| A14 | FK cascade: parent row with a bad date quarantined, its children leave the output | parent kept with its real date | F1b |
| A15 | Nested: a bucket_perturb child of `nested` with a bad cell raises the same record as the plain column | silent | F1b |
| A16 | `when:` gated, pandas: unselected rows carry a conflicting format, but detection uses only rows the handler receives; a bad selected cell reports its full-frame index through `_when_gate.py`, and an unselected bad cell gives no error | silent | F1b |
| A17 | `when:` gated, explicit format, native: `run_kernel_step_masked` rebases bucket_perturb positions through `selected`; records equal the explicit-format pandas twin | silent | F1b |
| A13a | Plan compile stores `quarantine_covers_format_error` only when quarantine is enabled and covers the trigger. YAML round-trip preserves it, an old plan with the field absent reads `False`, and a wrong stored type is refused | no Plan fact | F1c |
| A13b | For one quarantine config, capacity, `_job_estimate`, `--explain`, and the executed route all report the resident route and the same new route reason. Without coverage, all four keep the out-of-core decision. Direct `check_out_of_core_compatibility(plan, ...)` and its public export keep the old signature. After the engine repin, the platform `estimate_child` contract test calls root `decoy_engine.estimate_job` and reports the same resident estimate | callers can disagree when quarantine is threaded selectively | F1c |
| A18 | A chunk-eligible bucket_perturb column with quarantine covering `format_error` either finishes resident with the bad row quarantined, or fails before output with `reasons.decoy.ROW_ERRORS_FAILED`; it never succeeds on a chunked route with the source value present | no bucket_perturb row error today | F1b |
| S1 | Sentry `tests/sentry/test_no_silent_passthrough.py`: for each strategy in `SCALAR_HANDLERS`, one adversarial non-null case per declared trigger (and one plain case for a strategy with none). The case passes if the output differs from the source after normalization (`str(v).strip()` on both), or a RowError with the declared trigger is recorded, or the run raises. A strategy with no case and no allowlist entry fails. The allowlist holds `passthrough`, `shuffle`, `text_redact` (non-match) and `geo_generalize` (short zip), each with a written reason | bucket_perturb fails it | F1b |
| S2 | Sentry (same file): the set of (strategy, trigger) pairs observed in S1 equals the pairs declared in `_capabilities` `row_error_modes`; for strategies that have an `OperatorSpec` (`_operator_registry.py:188`, `:257`, `:277`), it equals the `reduce_row_error:<trigger>` entries in `routed_diagnostics` | bucket_perturb undeclared | F1b |
| G-ZIP | geo_generalize: an input zip with 3 or more digits never equals the normalized source | guards the allowlist entry | F1b |

S1 and S2 are registered in `SENTRY_PATHS` so `scripts/dev/gates.sh` runs them, and `tests/sentry/test_sentry_manifest.py` stays green. Seeded-bypass proof for S1 (cross-cutting rule): in a scratch copy, register a test strategy that returns its input; S1 must go red. Record it.

Existing tests that use unparseable bucket_perturb fixtures (about 30 files, among them `tests/unit/execution/test_bucket_perturb.py`, `tests/physical/test_shadow_bucket_perturb.py`, `tests/native/test_chunked_bucket_perturb_parity.py`, `tests/parity/test_phase_d_d1b1_bucket_*.py`, `tests/parity/test_phase_d_d2c_iii_bucket_*.py`): in F1a kernel callers unpack the new tuple; in F1b route and parity tests that asserted passthrough flip, in the same commit, to assert the same `RowErrorsFailedError` on both legs. The gate diff-checks every test edit for weakened assertions (memory builders-route-around-divergence).

## 6. Reuse inventory

- `RowError`, `drain_row_errors`, `RowErrorsFailedError`, the D8 quarantine rule: reused as-is.
- `native_date_shift` return shape and the `run_kernel_step_masked` rebase through `selected`: the pattern for `native_bucket_perturb`.
- `date_shift_row_errors` (`_sequential_native_ops.py`): generalized to `format_error_row_errors(strategy, ...)`, not copied.
- `format_error_records` (`native/_chunked_row_errors.py`): reused with the strategy key.
- `chunk_row_error_summary` (`_row_error_summary.py:147`): reused for every chunked raise.
- `_DEFERRED_GROUP_B` pattern in `out_of_core/_compat.py`: reused for the quarantine reroute.
- `_COMMON_FORMATS` and the 200-row sample of `transforms/date_shift._detect_format`: reused by the majority detector.
- `SCALAR_HANDLERS` (`execution/_strategies/__init__.py:48`): the sentry's source list.

## 7. Defect classes

| Class | Name | Closing structure | Sentry or property test | Mutation that must go red |
|---|---|---|---|---|
| 1 | value leak (unparseable value kept in clear text) | kernels return positions; handler and every native caller turn them into RowErrors | S1 no-silent-passthrough sentry over `SCALAR_HANDLERS`; A1 to A18 | drop the `ctx.row_errors.extend` in the handler; S1 and A1 go red |
| 2 | cleanup on failure | out-of-core raise happens before publish; publish-unit staging cleanup reused | A6, A12 assert no published file and no staging dir | move the raise after publish; A6 goes red |
| 3 | state across chunks | records stay chunk-local; the offset lives only in the chunk summary | A5, A9, A12 assert chunk-local `row_index`, `chunk_index` and `chunk_row_offset` | pass `chunk_row_offset=0` to `chunk_row_error_summary` in the bucket leg; A5 goes red |
| 4 | route divergence | one return shape for both kernels; autodetect exists only in the resident pandas handler; every other leg refuses it by admission | A3a asserts the companion decline and pandas record parity; A8 to A10 and A17 cover explicit-format route parity | change the detector sample from `head(200)` to `tail(200)`; A3a changes the winner and goes red |
| 5 | referential integrity | quarantine FK cascade reused | A14 | skip the cascade for format_error; A14 goes red |
| 6 | untrusted input | the bad cell is untrusted text; it never reaches a reason, log or exception context | P1 value-free reason check; `__context__ is None` on the raise | put the value in the reason; P1 goes red |
| 7 | TOCTOU / check-then-use | N/A: there is no separate check step; the kernel reports what it parsed in the same pass |  |  |
| 8 | weak tests | route tests flipped to assert equal errors on both legs, never deleted | gate diff-check of test edits | change a test to `pytest.raises(Exception)`; the gate rejects it |
| 9 | refactor drift (reason string copies) | one `format_error_reason` registry | P1 grep sentry: the date_shift reason literal only in the registry | re-add a literal copy; P1 goes red |
| 10 | frozen contract change | `RowErrorRecord` shape unchanged; `FORMAT_ERROR_REASON` kept as alias; behaviour change in CHANGELOG | compatibility contract tests unchanged and green | remove the alias; the import test goes red |

## 8. Frozen contracts

- `RowErrorRecord` and the row-error summary shape: unchanged.
- `apply_bucket_perturb` and `native_bucket_perturb` are internal (not in `decoy_engine.__all__`); their return type changes. Check the frozen-surface map (engine #599) before merge; if either is listed, the slice carries a FROZEN note.
- `native/_date_shift_ext.FORMAT_ERROR_REASON` stays importable for one release.
- The new route reason in F1c is declared with `since=UNRELEASED` (`reasons/_types.py:23`).
- The behaviour change (pass to fail on bad dates) is pre-GA and goes in CHANGELOG.

## 9. Slices

Each slice is green on its own head. F1-0, F1a and F1a2 change no behaviour. F1b turns errors on for every leg in one slice, with the parity and route test flips. F1c adds the reroute.

| Slice | Repo | Risk | Production files (max 10, 800 lines) | Tests |
|---|---|---|---|---|
| F1-0 reason registry, generic chunked and shadow carriers (after 24zb E1 merges) | engine | R1 | `execution/_row_errors.py`, `execution/native/_date_shift_ext.py`, `execution/_strategies/_date_shift.py`, `execution/_sequential_native_ops.py`, `execution/_sequential_native.py` (rename import at `:88` and call at `:553`, net lines 0 or less), `execution/native/_chunked_row_errors.py`, `execution/native/_chunk_masking.py`, `execution/native/_chunked_entry.py` (generic type at `:311`, generic call at `:348`), `execution/physical/_shadow_operators.py` | P1; existing date_shift route tests unchanged and green |
| F1a kernel return shape, every caller unpacks | engine | R1 | `transforms/bucket_perturb.py`, `transforms/date_preserve.py`, `execution/native/_bucket_perturb_ext.py`, `execution/_strategies/_bucket_perturb.py`, `execution/_sequential_native_ops.py`, `execution/native/_operator_step.py`, `execution/out_of_core/_mask_group_c.py`, `execution/out_of_core/_bucket_native.py` | P2; kernel-caller unpacking in existing tests; all outputs unchanged |
| F1a2 out-of-core chunk context, behavior-neutral | engine | R1 | `execution/out_of_core/_mask.py`, `execution/out_of_core/_stream_driver.py`, `execution/out_of_core/_rewrite_pass.py` | P3; existing output and route parity; no raise is enabled |
| F1b errors on, every leg | engine | R2 | `transforms/bucket_perturb.py` (resident-pandas majority detector, docstrings), `execution/_strategies/_bucket_perturb.py`, `execution/_sequential_native.py` (net lines 0 or less), `execution/_sequential_native_ops.py`, `execution/native/_operator_step.py`, `execution/_operator_registry.py`, `execution/native/_capabilities.py`, `execution/out_of_core/_mask.py`, `execution/out_of_core/_mask_group_c.py`, `execution/out_of_core/_bucket_native.py`; docs: `config/_validators.py` docstring, `docs/qa/07-mask-dates-and-numbers.md`, `docs/strategies.md`, CHANGELOG | A1 to A12, A14 to A18, S1, S2, G-ZIP, `test_capabilities.py` pins, parity and route test flips |
| F1c out-of-core quarantine reroute | engine | R2 | `plan/_types.py`, `plan/_compile.py`, `plan/_serialize.py`, `execution/out_of_core/_compat.py`, one `reasons/route/` catalog file (one new code, `since=UNRELEASED`) | A13a, A13b; plan-version and frozen-surface contract tests |

Expected size: F1-0 about 120 lines of source, F1a about 150, F1a2 about 45, F1b about 300, F1c about 100, plus tests. Every slice has at most 10 production files. No new public names in `decoy_engine.__all__`.

Size census: `execution/_sequential_native_ops.py` is 594 lines on `13c95c7de` and gets a new census entry in F1-0. `execution/out_of_core/_compat.py` is 586 lines and gets a new census entry in F1c. Each entry in `tests/sentry/test_module_size.py` has at most 20 lines of headroom and a decomposition note. These are new census entries, not raised pins. `_sequential_native.py` keeps its existing 700 ceiling, with a net line change of zero or less. `native/_chunked_entry.py` keeps its existing ceiling.

### 9.1 Placement

| New thing | Where | CODEMAP reason | Sits beside |
|---|---|---|---|
| `format_error_reason()` | `execution/_row_errors.py` (existing file) | the module that owns `RowError` | `drain_row_errors` |
| `format_error_row_errors()` | `execution/_sequential_native_ops.py` (existing file) | replaces `date_shift_row_errors` there | `_bucket_apply` |
| `apply_excluding_preserved_with_errors()` | `transforms/date_preserve.py` (existing file) | preserve helpers live there | `apply_excluding_preserved` |
| `_detect_majority_format()` | `transforms/bucket_perturb.py` (existing file) | bucket_perturb's own transform module | `apply_bucket_perturb` |
| `test_no_silent_passthrough.py` | `tests/sentry/` | sentries live there, run by `SENTRY_PATHS` | `test_operator_registry_sentry.py` |
| new route reason | `reasons/route/` existing part file | route reasons catalog | the date_shift deferral codes |

No new production file or directory. `_shadow_operators.py` and `_operator_step.py` are on the physical-seam allowlist already; check each edit stays inside it.

### 9.2 Order, release and repin

- Order: 24zb E1, then F1-0, then F1a, then F1a2, then F1b, then F1c.
- Reason-fixture merge order: prop-batch E-F0, then F1c. WF-R1 does not edit a manifest fixture and is not in this chain. On a conflict in the working reason manifest fixture, keep both additions. New codes use `since=UNRELEASED`; release prep stamps the version. Nobody edits the release pin `tests/fixtures/f29/reason-registry-release.json`.
- Release: F1-0, F1a and F1a2 may ship in any engine tag because they do not change behavior. F1b may ship alone: out-of-core with quarantine fails closed until F1c, which is safe. F1c follows in the next tag.
- CLI repin (row 77 train) after F1b's tag. The CLI needs no source change. One CLI e2e test goes in with the repin: a bad date in a bucket_perturb column, no quarantine. It asserts the named exit constant the CLI gives for an engine `DecoyError` today (expected `EXIT_RUNTIME`, 3; the builder confirms from `src/decoy/cli/run/_errors.py` and pins the constant by name), that stderr names the column and `format_error`, and that stderr does not contain the cell text.

## 10. Pre-mortem

- A customer config that ran clean now fails. Expected and wanted (it was shipping real dates). The CHANGELOG line and the error text name quarantine as the way to keep going.
- The majority detector picks a different format than today for a column where today's all-or-nothing detector found one: it cannot, because a format that parses every sample value has the highest count; ties keep today's order. A3a and the goldens pin it.
- A builder makes parity tests green by changing both legs to pass through. Blocked by S1 and the gate diff-check.
- A builder lands F1b's handler change without the seq-native seam: the parity suites go red on the same head. That is why both are in F1b.
- The Rust kernel may not expose unparseable positions. Check before F1a: if it cannot report them, compute them in Python after the call (input non-null, parse failed under the resolved format), as `native_date_shift` does. Do not change the Rust ABI.
- `_sequential_native.py` grows past its pin. Forbidden; the RowErrors are built in `_sequential_native_ops.py`.
- The out-of-core reroute changes the route for quarantine configs. A13b pins every reporting surface and the executed route.

## 11. Owner answers (F-1)

- Q1 answered (owner, 2026-11-16, recommended): out-of-core with quarantine covering `format_error` reroutes bucket_perturb to the resident route, as date_shift does. Slice F1c.
- Q2 answered (owner, 2026-11-16, not the recommendation): detect the format over the parseable majority, so only the unparseable cells become format errors; if no format fits any value, every non-null cell is a format error. Section 3, item 2; tests A3a, A3b.

## 12. Roadmap row for F-1 (ready to paste)

| 24zn | F1-BUCKET-FMT (finding F-1, 2026-11-16): `bucket_perturb` records a `format_error` row error for every unparseable date cell, on every route, as `date_shift` does. Without `date_format` the resident pandas handler uses the format that parses the most sample values, so one bad date is one error. Other legs refuse autodetect. Out-of-core fails closed, or goes to the resident route when the compiled Plan says quarantine covers `format_error`. A sentry checks that no mask strategy passes non-null input through silently | engine | PLANNED. Plan: engine `plan/f1-bucket-perturb-and-unplanned` (docs/plans/2026-11-16-f1-bucket-perturb-and-unplanned.md, rev 3), slices F1-0, F1a, F1a2, F1b, F1c | finding F-1; 24zb E1 | none |

## 13. Review round 1 map (Dennis on `56cbc8901`)

| Finding | Where resolved |
|---|---|
| H1 slices not green alone | section 9 (F1-0 and F1a behaviour-neutral; F1b changes every leg, seq-native seam and parity flips together; A14 in F1b; `_bucket_native.py:271` unpack in F1a with the return change), section 3 item 5, section 10 |
| H2 chunk-local row indexes | section 3 items 7 and 8; tests A5, A6, A9, A12; class 3 row |
| H3 WF-R1 tombstone details | B1.1 |
| H4 GATE-07 one predicate | B1.2 (G-eng) |
| M1 fourth date_shift literal, 24zb E1 | section 3 item 3; F1-0; section 9.2 order |
| M2 reroute plumbing and fixture order | section 3 item 8; F1c files; section 9.2 |
| M3 S2 per (strategy, trigger) | S2; section 3 item 6 |
| M4 S1 normalization, file, gates, geo_generalize | S1, G-ZIP, section 1.1, placement table |
| M5 Q2 majority detection | section 3 item 2; A3a, A3b; section 11 |
| M6 nested and `when:` tests | A15, A16, A17; section 4.2 |
| M7 `_sequential_native.py` size | section 3 item 5; F1b row; section 10 |
| L1 docs | section 3 item 9; F1b row |
| L2 W2 allowlist file | B1.1 |
| L3 repin exit code | section 9.2 |
| L4 remote sources at validate | B1.2 (G-cli) |

## 14. Review round 2 map (Dennis on `50568d034`)

| Finding | Where resolved |
|---|---|
| H1 `V1`, quarantine routing callers disagree | section 3 item 8; A13a and A13b; F1c row. The Plan owns the compiled fact and the compatibility signature does not change |
| H2 `DESIGN`, duplicate out-of-core raise paths and file cap | section 3 items 7 and 8; new behavior-neutral F1a2; F1b uses the one `mask_batch` raise helper; every slice stays at 10 production files or fewer |
| M1 `V2-LOG`, generic carriers missed in F1-0 | section 3 item 5; F1-0 row names `_sequential_native.py` and `native/_chunked_entry.py` with exact sites |
| M2 `V2-LOG`, autodetect scope and weak mutation | section 3 item 2; A3a, A4 and A16; class 4 mutation. Only resident pandas detects, and the tail-sample mutation changes A3a's winner |
| M3 `V1`, no chunked quarantine exit | section 4.1 and A18 |
| M4 `V2-LOG`, WF-R1 fixture coupling | section 9.2 and B1.1. WF-R1 edits no fixture and W2 names the release-pin allowlist |
| L1 `V2-LOG`, size census wording | section 9 size census. The two files get new entries with at most 20 lines of headroom, not raised pins |
| L2 `V2-LOG`, missing predicate name and placements | B1.2 names `_degenerate.py`; B1.4 places G-eng, G-cli, GC1 and GC2 |

# Part B. Unplanned rows

Method: every row in ROADMAP section 5 (CLI origin/main) that is not DONE, MERGED or deferred, minus the excluded sets (Windows chain 6 and 89; feat/v1plus-* and V2; remote-owned LIB, GEN-REL, GEN-INHERIT, SCAN-ML CLI, F22, F25, F26), minus rows with a plan branch, a plan file on main, or a plan cited in the row. Plan branches were read with `git ls-remote origin 'refs/heads/plan/*'` on both repos.

Already planned today and excluded: 24e, 24zb, 24zi to 24zl, 30, 31, 32, 32c, 24z, 24za, 24zc, 24ze, release rows 46, 47, 76, 78, 88, 90, 90a, 91, and the fit rows. Planned elsewhere: 3 (ci-e2), 16 and 56 (storm-removal), 24p, 24q, 24zf, 27, 29, 32a, 32b, 61 to 64, 66, 68 to 70, 72, 79, 85.

## B1. Rows planned in full here

### B1.1 Row 17 WF-R (QA check EXIT-07)

Verdict: CLI half DONE at CLI `cfdee4ef` (#146, 2026-11-09). It removed the pointer `decoy-platform/docs/guides/cli-yaml-workflows.md` from `src/decoy/cli/explain.py`; no workflow pointer is left in that file. Engine half NOT DONE: `reasons/platform/_part1.py:72` to `:74` export `WORKFLOW_RESTART_INTERRUPTED`, `WORKFLOW_STEP_FAILED`, `WORKFLOW_STEP_NOT_RUN` as live codes (declared at `reasons/platform/_part1.py:239`, `:244`, `:325`). No engine code uses them; the parked platform uses them in its workflow runner tests and docs.

V1 behaviour: the three codes become tombstones. They move to a new `reasons/platform/_retired.py` in the `reasons/route/_retired.py` pattern, with `deprecated_in=UNRELEASED` (`reasons/_types.py:23`; release prep stamps the version, `tests/unit/test_reason_release_pin.py:5` to `:9`) and `replaced_by=None` (workflows are retired with no replacement; `check_integrity` allows a deprecated entry with no replacement). Everything else stays byte-identical: owner, kind, severity, outcome, summary and `since="1.5.0"`. Two codes are declared through the PlatformJobLog declarer (`reasons/platform/_part1.py:80`) and `WORKFLOW_STEP_FAILED` through the PlatformResponse declarer (`:318`); `_retired.py` uses the same two declarers. They stay resolvable, so the parked platform still reads its old records. WF-R1 does not edit a manifest fixture. The release pin `tests/fixtures/f29/reason-registry-release.json` stays byte-identical.

Acceptance tests (red first):

- W1: for each of the three codes, `reasons.find("platform", code).deprecated_in == UNRELEASED` and every other `ReasonSpec` field equals its value on `13c95c7de` (compare the dataclass minus `deprecated_in`). Fails today: `deprecated_in` is None.
- W2: residual sentry: the three spellings appear only in `reasons/platform/_retired.py`, `tests/unit/safe_output/test_platform_reasons.py`, and the explicit allowlist entry `tests/fixtures/f29/reason-registry-release.json`. That test's expectations at `:56`, `:71` and `:110` read the codes from `_retired`. No other manifest fixture is allowlisted. Fails today: the spellings are in `_part1.py`.
- W3 (CLI, after repin): `decoy explain` output and every reason code the CLI can print contain no `workflow_` code (EXIT-07). Passes today for the pointer; added as a guard.

Failure modes: the release pin is a frozen surface and remains unchanged. The platform keeps importing the names from `reasons.platform`, so `reasons/platform/__init__.py` re-exports them from `_retired`.

Slice WF-R1: engine, R1, files `reasons/platform/_part1.py`, `reasons/platform/_retired.py` (new, beside `_part1.py`, mirrors `reasons/route/_retired.py`), and `reasons/platform/__init__.py`. W3 rides the next CLI repin. Then row 17 closes and EXIT-07 can run.

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
- G7b: a snapshot with one negative weight and a positive weight sum: refused with `statistical_stats_degenerate` at compile, at window admission and in the sampler. Fails today: the sampler accepts it. A NaN weight: same.
- G7c: every sampler degenerate site raises through the predicate (mutation: delete one rule from the predicate; the matching G7 or G7b case goes red at compile and at run).
- GATE-08 (row 23) then runs `decoy run` on the same configs and expects the same exit.

Design:

- G-cli (CLI, R2): the preflight layer calls `prepared_sources(validated_config, base_dir=config.parent)` after `_check_source_files` passes, and turns a `PipelineValidationError` into a preflight error finding with its code. One choke point, no second column check. DuckDB sources use the schema path `run` uses (`for_supplied` with `DESCRIBE`), which #255 wires. Files: `src/decoy/cli/gate/_layers.py`, plus `src/decoy/cli/preflight.py` if the finding helper lives there. Tests: G5, G5b, G6.
- G-eng (engine, R2): one degenerate-snapshot predicate, `generation/statistical/_degenerate.py::check_degenerate(spec) -> None`, raises `STATISTICAL_STATS_DEGENERATE`. It owns every degenerate rule that today is spread over six sampler sites (`generation/statistical/_sample.py:419` to `:521`: edges and counts shape, `sum(counts) <= 0`, `sum(weights) <= 0` for categorical and conditional rows) and `_numeric_shape.py:150`. Three callers use the public `generation.statistical` package API: the sampler (raises from the predicate instead of its own checks), window admission (`generation/_window_admission.py:241` `_check_statistical`, which keeps its own unbounded checks) and the compile check `check_statistical_columns` (`plan/_checks.py:286`), which `decoy validate` runs. One rule, one code, three callers.
  - Weight rule, decided once: refuse a negative or non-finite weight or count anywhere, as window admission does for length edges. Today the sampler checks only `sum(weights) <= 0`, so a snapshot with one negative weight and a positive sum samples at run today and is refused after G-eng. That is a run behaviour change, recorded in CHANGELOG, with test G7b.
  - Files: `generation/statistical/_degenerate.py`, `generation/statistical/__init__.py`, `generation/statistical/_sample.py`, `generation/statistical/_numeric_shape.py`, `generation/_window_admission.py`, and `plan/_checks.py`. Tests: G7, G7b at engine compile and run level, and G7 in the CLI after repin.

Failure modes: the gate must not read data rows (the header read is the one `run` makes); a config whose source is absent stays a "file not found" finding, not a crash; findings are value-free (declared names only, which are config text).

Remote sources (review L4): for an `s3://` or `gs://` source, validate does not open the object. `prepared_sources` is called only for sources whose path is local (the same `_has_path` filter, plus a local-path test); each remote source gets a preflight warning finding "declared columns not checked: remote source, checked at run", and `decoy run` still refuses before any data row (CLI #255). Reason: validate is an offline gate and must not need cloud credentials. Test G5c: an `s3://` source with a missing declared column gives the warning at validate (exit 2 with `--fail-on-warning`, else 0) and no network call (the client factory is patched to fail).

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

### B1.4 Placement

| Slice | New or changed thing | Where | CODEMAP "Where Things Go" row | Sits beside or uses |
|---|---|---|---|---|
| G-eng | new `_degenerate.py` and its public export | `src/decoy_engine/generation/statistical/_degenerate.py`; export from `generation/statistical/__init__.py` | engine CODEMAP line 63 places statistical-generation modules in `generation/statistical/`; line 259 places generation code in `generation/` | `_numeric_shape.py`; callers import the package API, not the private module |
| G-cli | existing preflight layer and optional existing finding helper | `src/decoy/cli/gate/_layers.py`; `src/decoy/cli/preflight.py` only if its existing helper owns the finding | CLI CODEMAP line 52 places the pre-run gate in `src/decoy/cli/gate/`; no new flat CLI module | `_run.py` and the existing preflight finding type |
| GC1 | existing list registries and readers | `src/decoy/cli/reference.py`, `src/decoy/cli/cockpit.py` | CLI CODEMAP line 48 records current command modules in the frozen flat folder; this slice adds no module | `_LIST_READERS`, `_SINGULAR_TO_PLURAL`, and the existing list command readers |
| GC2 | six new packaged templates | `src/decoy/templates/generate-{healthcare,banking,insurance,retail,telecom,hr}.yaml` | CLI CODEMAP line 65 places packaged templates in `src/decoy/templates/<name>.yaml` | `generate.yaml` and `_REGISTRY` in `src/decoy/templates/__init__.py` |

## B2. Rows not planned here, one line each

| Row | QA group held | What it needs |
|---|---|---|
| 18 R-c | groups 1 and 16 (INST-11, BLD-05) | Nothing to build. R-c shipped short of its list and later releases carry the rest. Owner Q3 answered: mark it CLOSED (folded into 77) so it stops holding groups. |
| 75 One CLI journey | group 15 (DOC-05) | A short plan after CLI delivery (61): write the V1 journey as numbered ids in `docs/`, one e2e test per id, and make `release-smoke.yml` cite the ids. CLI, R1. |
| 64b CLI-DB-SRC | group 6 | A plan after CLI delivery: `type: postgres` source through engine `postgres_snapshot`, the value-free connection reference, and a Postgres CI lane (CI-P2 markers). Engine and CLI, R2. |
| 80 F15 | group 4 | Plan after the STORM rename and SCAN-LIB: bound-baseline object and strict-drift block; scan-diff moves to engine `scan-diff/v1`. |
| 81 F16 | group 4 | Plan after the Phase 1 rows: selector grammar, prohibition predicates, 5-level precedence, disguises in the engine. Large; split before planning. |
| 82 F07 | none | Plan after the STORM rename: bounded path discovery, nested-path relations, JSONB coverage. |
| 83 F13 adapters | KEY-08 | Owner Q4 answered: Phase 2, not V1. Move the row out of V1; no plan now. |
| 84 F24 engine half | none | Small plan: add the ingestion peak to the estimator (engine #328); advisory only. |
| 86 F01 | group 6 | Plan after F22 settles: Postgres write target with staging, constraint and index restore, atomic publish, type-mapping report. Owner said CLI V1. |
| 87 F02 | group 6 | Plan after CLI-CLOUD and the F22 adapter: SFTP, cloud scan, subset against cloud, retry executor, content digest. |
| 54 H-1 E7 | none | Per file as blockers merge; the H-1 Wave B plan (platform `plan/h1-wave-b`) is the method. No new plan. |
| 48 to 53 H-1 | BLD-03 (46, 53) | Wave B plan exists (platform `plan/h1-wave-b`, rev 3 handoff); needs handoffs only. |
| 77 Later releases | never holds a group | Covered by the release-chain plan's train; no plan. |
| 92 REL-DOCS | DOC-01, DOC-06, DOC-07 | Plan is decoy-web-docs `DOCS-PLAN.md`; the host waits on REL-WEB Q1. |
| 94 CLI-REL | INST-11, BLD-06 | S0 is in the rel-gate and release-chain plans; the rest is the final release run. |

## B3. Owner answers

Answered by the owner on 2026-11-16 (relayed with Dennis round 1):

- Q1 (F-1): reroute out-of-core to resident when quarantine covers `format_error` (recommended). Slice F1c.
- Q2 (F-1): decided differently from the recommendation: majority-format detection, so only the unparseable cells are format errors; all cells only when no format parses any value. Section 3, item 2.
- Q3 (row 18): mark R-c CLOSED as folded into row 77 (recommended). This is a roadmap edit for the coordinator, not a slice.
- Q4 (row 83): F13 external adapters are Phase 2 (recommended); `env:` and file references stay the V1 secret sources.
- Q5 (row 24s): six separate template files (recommended).

No open owner question is left in this plan.

## Slice summary

| Slice | Row | Repo | Risk | Depends on | Release point |
|---|---|---|---|---|---|
| F1-0 | 24zn (F-1) | engine | R1 | 24zb E1 merged | any tag (no behaviour change) |
| F1a | 24zn | engine | R1 | F1-0 | any tag (no behaviour change) |
| F1a2 | 24zn | engine | R1 | F1a | any tag (no behaviour change) |
| F1b | 24zn | engine | R2 | F1a2 | next tag, then CLI repin with e2e test |
| F1c | 24zn | engine | R2 | F1b and E-F0 reason changes merged | next tag |
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

- F1-0, F1a, F1a2, F1b and F1c are merged with P1 to P3, A1 to A18, S1, S2 and G-ZIP green; F1b is released and the CLI is repinned with its e2e test; F1c is released. Row 24zn is DONE.
- WF-R1 is merged and released; W3 is green after the repin; row 17 is DONE.
- G-cli and G-eng are merged; G5, G5b, G5c, G6, G7, G7b and G7c are green; row 24b is DONE.
- GC1 and GC2 are merged; C1 to C5 are green; row 24s is DONE.
