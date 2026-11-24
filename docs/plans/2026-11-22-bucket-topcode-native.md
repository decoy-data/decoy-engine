Status: plan (revision 3, 2026-11-24; after Dennis r1; anchored to cb06f318e)

# BUCKET-TOPCODE-NATIVE: vectorized Arrow operators for `bucketize` and `top_code`

Owner: Cam. Author: Opus (plan author). First written 2026-11-22. Roadmap row: BUCKET-TOPCODE-NATIVE (group mask; V1 fast-path audit, vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`). Engine only. The CLI gets it through its next engine pin bump.

Anchors: a path with no prefix is under `src/decoy_engine/`. Read at engine `origin/main` `cb06f318e`. origin/main has since moved to `9f7bb1f4a` (#788, scratch root); that change touches none of the files below. Must stay consistent with `plan/route-label-truth` (an Arrow backend is not "native_executed"), `plan/native-threads-default`, `plan/when-reads-source` and `docs/plans/2026-11-21-column-shape-rule.md` (COLUMN-SHAPE-RULE). This plan does not depend on `plan/per-column-routing` (not merged): native admission stays per table.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `profiles/local-operations.md`, `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md`.

Risk: R2 (two anonymisation strategies used by the HIPAA template move off pandas on two routes; two named byte changes, both crash or silent-precision fixes in the oracle). Plan review: Dennis, then Codex. Code gate: Codex; Dennis on S1b.

Owner direction (2026-11-22): every strategy runs its fastest path by default; pandas only where no faster build exists, named on the run card and in the docs; faster and more robust wins even when bytes change, and every byte change is named; output stays deterministic per seed. Engine-gap deadline 2026-12-15.

## 0. Revision 3 changes (after Dennis r1, NO-GO)

Revision 3 narrows V1 to the unified slice and chunked routes on `int8`-`int64`, `uint8`-`uint32` and `float64` sources, and moves every cut case to section 13 with a reason. Per finding:

| Finding | Resolution | Where |
|---|---|---|
| H1 int64 wrap | Fixed. The integer floor path is gone. Arithmetic mirrors the oracle in float64 (`pc.divide`, `pc.floor`, `pc.multiply`), which a probe shows bit-identical to numpy. For an integer width, a value that is non-finite or has magnitude at or above 2**53 takes a named exit (`format_error`, reason `value is out of range under bucketize`) in both the oracle and the operator. Every integer step after that check uses `*_checked` kernels and safe casts. Byte changes B2 and B3. P2 cells at int64 min, int64 max, `max - w + 1`, `2**53 - 1`, `2**53`, `1e19`, under every format. | sections 4, 5, 9, 10 |
| H2 width type, not source type | Fixed. Section 4 has the 2 x 2 table (source int or float, by width int or float) with the label rule, exit and byte entry per cell, per format. The kernel branches on the width type, as the oracle does. B3 corrected: it applies to integer widths only; a float width over `inf` keeps writing `inf` and `inf-inf`, unchanged. | section 4 |
| H3 float32 | Cut to V2-LOG. `float32` declines to the handler on both routes (P2 decline cell). | sections 4, 13 |
| H4 B2 parity on null-bearing ints | Fixed by removing the cause. Revision 2's "exact large integers" (old B2) is dropped. Both oracle and operator convert to float64 with round-to-nearest (probe: equal), and both apply the 2**53 exit to the float64 value, so a null-bearing int64 column (float64 on pandas ingest) and a null-free one (int64) give the same result on every route. No change to `lossless_int_columns`. | sections 4, 10 |
| H5 chunked gate | Fixed. The bucketize null-count gate stays (old B4 cut). The native chunked leg reconciles a zero-row or all-null chunk to Arrow `null`, the oracle chunked leg's own per-chunk type (probe), through the same reconciliation bucket_perturb uses, keyed by the registry's `null_on_empty` fact instead of an `isinstance`. Both legs then type every chunk the same way, so no schema-rule pin is needed and none is added. See the note below. | sections 4, 5 |
| H6 B1 type pin | Fixed by option (b). Old B1 is dropped. `full_frame_assembly="null_on_empty"` matches the oracle on every route: probe on full frame, unified and chunked, int and float sources, gives `null` for an empty or all-null column and `string` otherwise. No pin mechanism is added. P4 has the degenerate cells on every route. | sections 5, 9 |
| H7 out-of-core | Cut to V2-LOG. Out-of-core refuses bucketize today (`out_of_core/_compat.py:71-83`, `out_of_core_row_error_strategy_unsupported`) and has no top_code path. The route table is corrected. Nothing changes on that route. | sections 4, 13 |
| H8 binary reason channel | Fixed. The `format_error` reason becomes an `OperatorSpec` field. `format_error_row_errors` reads it by operator id; the chunked channel carries the operator id per column; the `bucket_columns` `isinstance` set in `_chunked_entry.py:344-350` is deleted (the file shrinks). | section 5 item 6 |
| H9 fan-out | Fixed by cutting sequential (V2-LOG) and out-of-core. No new module under `execution/` or `execution/out_of_core/`. The one new source module is `kernel/_bucket.py` (`kernel/` has 5 entries, not frozen). `_sequential_native.py` is not touched. | sections 6, 7 |
| H10 P5 expectation | Fixed. Chunked: the job fails with `RowErrorsFailedError`, chunk-local `row_index`, records equal to the oracle chunked leg. Full frame and unified: quarantine or fail per the job's row-error policy, records equal. | section 9 P5 |
| M1 | S1 split into S1a and S1b, each about one builder-day, with a full file list and a size budget per file. | section 6 |
| M2 | top_code routes both its obligations: `routed_diagnostics={"reduce_row_error:format_error", "reduce_warning:top_code_generalized"}`. The capability row keeps `format_error` because the handler's object-column path still emits it; the operator never does on typed input. Unified computes the warning counts over the whole source column (the oracle's scope); chunked emits per chunk, as the oracle chunked leg does. P4 asserts warnings and counts. | sections 5, 9 |
| M3 | Settings resolve once into `BucketizeParams` and `TopCodeParams` in `native/_operator_params.py`; config declines happen at admission in `_operator_config_rejections.py`. `top_code_settings` never raises; an unresolvable config declines and the handler raises its existing `StrategyError` on the oracle route. | section 5 items 2, 3 |
| M4 | top_code in-range rendering specified (section 4), with P2 cells `-1e300`, `-2.0**63`, `-0.0`, `-inf` with no floor. | sections 4, 9 |
| M5 | Verified. Unified sees the post-cast table: `_pipeline_full_frame.py:164-167` runs `cast_run.pre_mask` before `maybe_run_unified_slice`, so an F06-declared integer column reaches the operator as `int64` and is admitted. Chunked casts inside each chunk lane, and `real_type_decline` reads the first raw schema (`string`), so the same column declines on chunked with `source_type_not_numeric`. P4's F06 cell expects exactly that. | section 9 P4 |
| M6 | The P10 AST test also asserts `kernel/_bucket.py` imports nothing from `decoy_engine.execution`. The mutation is retargeted to that test. | sections 5, 8 |
| M7 | Old B2 is gone, so there is no exactness claim to prove. P3b is a property test of the float mirror itself (operator against the oracle formula, random ints and floats, seven widths). | section 9 |
| M8 | New route reason `source_type_not_numeric`, registered in `reasons/route/_added.py` with `since=`, and `RouteDeclineCode.SOURCE_TYPE_NOT_NUMERIC`. A catalog entry, not an allowlist, census or baseline. | section 4 Codes |
| L1 | P9 inlines the hipaa template's top_code column config. | section 9 |
| L2 | CI runs the locked pyarrow (24.0.0 in `uv.lock` at the anchor); P1 to P3 run on it. | section 11 |
| L3 | Folded into H8: the reason text is named and pinned in P5. | |

Note on H5 (a deliberate difference from the review's suggested fix). The review asked for a `_chunked_schema_rule.py` pin. A pin to `string` would make a whole all-null column `string` on chunked and `null` on full frame, a new recorded route difference. With the null-count gate kept, chunked bucketize only sees null-free sources, and top_code's oracle chunked leg already types an all-null chunk `null`. Matching that per chunk on the native leg (the bucket_perturb precedent, `native/_chunk_masking.py:254-259`) keeps every route equal to the oracle with no new rule. If the gate is lifted later (V2-LOG), the pin comes with it.

Unchanged from revision 2: E3 narrowed the source domain to typed numbers; the width is read only through `contracts/bucketize_width.py` via the handler module; the statistic check is an AST test, not a registered sentry; no public signature changes (#763).

No merged engine PR already does this work (searched merged PRs for "bucketize native" and "top_code native"). #790 (open, `date_shift` native on typed `date32`) is the nearest sibling; it touches `_date_shift_ext.py`, which S1b also edits (section 11).

## 1. Frame

`bucketize` and `top_code` have no entry in the operator registry (`execution/_operator_registry.py:131-312` lists passthrough, redact, truncate, text_redact, text_mask, hash, faker, categorical, bucket_perturb, group_key, date_shift, fpe). Today:

- `top_code` is row-local and CHUNK_SAFE, but excluded from the native route for lack of a kernel (`execution/native/_capabilities.py:281-302`); the unified slice sends it to full frame (`execution/physical/_shadow_full_frame.py:113-121`, `ADMITTED_GLOBAL_STRATEGIES`).
- `bucketize` runs chunked pandas only when the source is null-free numeric, because its pandas output type depends on chunk content (`execution/_chunked.py:21-33`; gate at `execution/_planner.py:508-526`). A column with nulls runs full frame. This plan keeps that gate.

Since E3, both strategies read only typed numbers: a typed integer or float column, a declared (F06) text column cast before masking, and for `bucketize` a decimal of precision 15 or less (`contracts/strategy_requirements.py:198-232`). Both are pure functions of the row's own value and config literals: the bucketize width from `width` or a preset through `contracts/bucketize_width.py`; the top_code `cap`, `over_label`, `floor`, `under_label` from config or the `hipaa_age` preset (`_top_code.py:396-460`). No threshold is ever derived from data. This plan keeps it that way and makes a test of it.

Oracle semantics on typed input (read at the anchor and probed with pandas 2.3.3, pyarrow 24.0.0):

- bucketize (`_bucketize.py:66-134`): `nums = pd.to_numeric(col, errors="coerce")`; `lower_f = np.floor(nums / width) * width`. Integer against float handling is decided by the width (`is_int_width`), not the source dtype. Integer width: `lower = lower_f.astype("Int64")`, range upper `lower + w - 1`, midpoint `lower_f + w / 2` cast to `Int64` only for an even width. Float width: float labels through `astype(str)`. An unknown format becomes `lower`. `declared_integer_output` keeps `lower` as `Int64`. Output is `formatted.where(nums.notna(), col)`, so NaN and null stay null.
- top_code (`_top_code.py:148-268`): bounds finite with magnitude below 2**53. A numeric column: over is `nums > cap`; under is `nums < floor` only when both `floor` and `under_label` are set; in range renders `astype(str)` for an integer dtype, and for a float dtype `str(int(v))` for an integral finite value, else `astype(str)`. top_code columns are in `lossless_int_columns` (`_fk_keys.py:369-395`), so a null-bearing integer column arrives as `Int64` and renders exactly. On a numeric column it never emits `format_error`. A `top_code_generalized` warning carries `over_count` and `under_count` for the frame it ran on.

Probed oracle behavior the design must keep or name:

1. Integer width over `int64` `2**63 - 1`, or a float `1e19`: `TypeError` crash. Over `inf` or `-inf`: `OverflowError` crash. Over `2**53 + 1`: label from the rounded float, `9007199254740990`. Over `-2**63`: label `-9223372036854775808`.
2. Float width over `inf`: `inf`, range `inf-inf`. No crash.
3. Degenerate types, every route, int and float sources: empty column `null`, all-null column `null`, otherwise `string`.
4. Float mirror: Arrow `cast(int64 -> float64, safe=False)`, `divide`, `floor`, `multiply` equal numpy's `np.floor(nums / w) * w` on 1,000,000 values (random full-range int64, random int64 within 2**53, random finite doubles from raw bits, uniform and normal floats) for widths 1, 3, 7, 10, 1000, 2.5, 0.1, 0.3: zero mismatches. pandas' float64 ingest of a null-bearing int64 rounds the same way as the Arrow cast.

### Measurement (decides Rust against Arrow)

Probe on the Dell node through `vm-run`, 1,000,000 rows, minimum of five runs (pyarrow 24.0.0, pandas 2.3.3):

| Case | pandas oracle logic | Arrow compute | Ratio |
|---|---|---|---|
| bucketize int64 with 1% nulls, width 10, `range` | 783 ms | 82 ms | 9.5x |
| bucketize float64, width 2.5, `range` | 2,065 ms | not run | |
| top_code int64 with nulls, cap 89 | 1,009 ms | 48 ms | 21x |
| Parquet write and read, bucket label strings | 149 ms | | |

Arrow compute is 48 to 82 ns per row; writing and reading the label column alone is about 149 ns per row. A Rust kernel could save at most the compute, below the I/O floor. Decision: **a vectorized Arrow operator (`ARROW_PYTHON`, `required_kernel=None`), no Rust.** This matches redact, truncate and text_redact (`execution/_operator_registry.py:142-171`). The 82 ms figure used integer arithmetic; the float mirror adds one cast and is rerun in the PR (section 9).

## 2. Established solutions

Fixed-width recoding is `floor(x / w) * w` everywhere (sdcMicro `globalRecode` with equal breaks, Polars `floor`); top-coding is a threshold compare with a replacement label (sdcMicro `topBotCoding`; HIPAA Safe Harbor age rule 164.514(b)(2)(i)(C)). Nothing to invent. Parsing text into numbers is the F06 boundary's job.

### Reuse inventory

- `kernel/` package ("Arrow kernels" row, `CODEMAP.md:122`, `:277`): the array functions go in `kernel/_bucket.py` beside `_scalar.py`.
- `execution/native/_kernels_scalar.py` (384 lines): home of `native_redact`, `native_truncate`; the two operator entries join it. It already imports a handler helper (`:55`), the precedent for section 5 item 2.
- `OperatorSpec.routed_diagnostics` (`_operator_registry.py:254`, `:275`) and the unified coordinator's row-error routing (`_unified_slice_admission.py:141-153`).
- `full_frame_assembly="null_on_empty"`, bucket_perturb's shape (`_operator_registry.py:252`), read by `physical/_shadow_assembly.assemble_column`.
- The chunked format-error channel (`native/_chunk_masking.py:274-280`, `native/_chunked_row_errors.format_error_records`, `native/_chunked_entry.py:344-380`), with its reason made a registry fact (H8).
- `_shadow_assembly.per_node_warnings` (`:124-134`), where fpe and text_mask add node warnings; top_code joins it.
- The width rule `contracts/bucketize_width.resolve_bucketize_width`, reached through `_strategies/_bucketize.py`; the top_code resolvers `_resolve_top_bound`, `_resolve_bottom_bound` (`_top_code.py:396`, `:424`), called, not copied.
- `native/_operator_params.py` and `native/_operator_config_rejections.py`: params built once, config declines at admission (`native/_plan.py:311-340`).
- Already present, no edit: `_technique_class.py:77,159`, `native/_determinism_protocol.py:82-83` (`DETERMINISTIC_NO_DRAW`), `_chunked_fk_vocab.py:52-53`, `_column_access.py:310-311`.

## 3. Guarantee and non-goals

After S1b:

1. A `bucketize` or `top_code` column whose source arrives as `int8`-`int64`, `uint8`-`uint32` or `float64`, with no `when:`, not an FK key, and an admitted config (section 4 Fields), runs the Arrow operator on the unified slice and on the chunked route (bucketize on chunked only when the existing null-count gate admits the table), at any row count.
2. Output equals the oracle row for row, type for type, on every admitted route, except the named changes in section 10, which are made in the oracle too.
3. Output type: `string`, or Arrow `null` for an empty or all-null column on full frame and unified, and for a zero-row or all-null chunk on chunked, as the oracle gives today.
4. Thresholds and widths are config literals or presets only. A test fails if the kernel module reads a column statistic.
5. Row errors (`format_error`, only bucketize with an integer width over a non-finite value or a magnitude at or above 2**53) match the oracle by table, column, row index, trigger and reason.
6. Any other input declines to the handler before masking with a coded reason, and the handler applies the E3 shape rule. The operator never decides a shape question.
7. Sequential and out-of-core behave exactly as on main.

Non-goals: Rust; data-derived bins; new formats or presets; text parsing; global `top_code_generalized` counts on chunked (known limitation, `docs/backlog/chunked-audit-evidence-row-indices.md`); everything in section 13.

## 4. Enumerations

### Arithmetic and labels: source type by width type (bucketize)

`f` is the source value as float64 (`cast(safe=False)` for an integer source, round-to-nearest, which is what pandas ingest and numpy division do). `lf = floor(f / w) * w` in float64. "Exit" means: a `format_error` row error with reason `value is out of range under bucketize`, the oracle keeps the source value in its frame (the pipeline quarantines or fails, D8), and the operator writes null at that position (never written: see P5).

| Source | Width int `w` (admitted below 2**53) | Width float `w` |
|---|---|---|
| int (`int8`-`int64`, `uint8`-`uint32`) | Exit if `abs(f) >= 2**53` (B2). Else `lower` = decimal of `int(lf)`; `range` = `lower` + `-` + decimal of `int(lf) + w - 1`; `midpoint`: even `w`, decimal of `int(lf + w / 2)`; odd `w`, float string of `lf + w / 2` | No exit. `lower` = float string of `lf`; `range` = float string of `lf` + `-` + float string of `lf + w`; `midpoint` = float string of `lf + w / 2` |
| `float64` | NaN: null. Exit if `inf`, `-inf` (B3) or `abs(f) >= 2**53` (B2). Else as the int row (labels `20`, not `20.0`) | NaN: null. No exit. `inf` gives `inf`, `inf-inf`, `inf`; `-inf` likewise; otherwise as the int row. Unchanged from main |

"Decimal of" is `pc.cast(int64 -> string)` after `pc.cast(float64 -> int64, safe=True)`; every value there is integral with magnitude below 2**54, so the safe cast cannot fail, and `add_checked` cannot overflow. "Float string" is `python_float_str` (section 5 item 1), equal to the oracle's `Series.astype(str)`. Per format and cell, P1 and P2 have one cell each (24 cells: 2 sources x 2 widths x 3 formats x finite and non-finite or out-of-range).

### top_code rendering (no exit; never `format_error` on typed input)

| Value | Rule | Example |
|---|---|---|
| null, NaN | null | |
| `f > cap` (compare in float64 when either side is float, exact int64 when both are integers) | `over_label` | `inf` is over |
| `f < floor`, only when `floor` and `under_label` are both set | `under_label` | |
| in range, integer source | `pc.cast(int64 -> string)` (oracle: `Int64.astype(str)`, exact) | `4611686018427387911` |
| in range, float, integral, finite, magnitude below 2**63 | `cast(float64 -> int64)` then string | `-0.0` gives `0`; `-2.0**63` gives `-9223372036854775808` |
| in range, float, integral, finite, magnitude at or above 2**63 | `str(int(v))` per value in Python (rare; exact by construction) | `-1e300` (no floor) gives the 301-digit integer |
| in range, float, non-integral or non-finite | `python_float_str` | `67.5`; `-inf` with no floor gives `-inf` |

### Exit paths (per value)

1. null or NaN: null, no error.
2. bucketize, integer width, finite, magnitude below 2**53: labelled (table above).
3. bucketize, integer width, non-finite or magnitude at or above 2**53: exit (B2, B3).
4. bucketize, float width, any non-null value: labelled, no exit (unchanged).
5. top_code, any non-null value: over, under or in-range label.
6. A checked kernel or safe cast that raises after the exit check: unreachable by the bounds above; if reached, the `ArrowInvalid` propagates as a crash in the operator, and P2 proves no cell reaches it.
7. Config the operator does not admit (section 4 Fields): declines at admission; the oracle route runs the handler, which raises its existing `StrategyError` at preflight or run, before any output, as on main.

### Inputs per array type

| Arriving array type | Operator | Code on decline |
|---|---|---|
| `int8`-`int64`, `uint8`-`uint32` | admitted | |
| `float64` | admitted | |
| `float32` | declines (V2-LOG: the oracle computes and prints in float32) | `source_type_not_numeric` |
| `uint64` | declines (V2-LOG) | `source_type_not_numeric` |
| `string`, `large_string` (an undeclared or chunked-raw column) | declines | `source_type_not_numeric` |
| `decimal128`, `bool`, any other | declines | `source_type_not_numeric` |

The admitted set is the spec's `unified_resident_types`, one frozenset in the registry, read by unified admission and by the chunked type check.

### Routes

| Route | Today | After |
|---|---|---|
| Unified slice | full frame (top_code via `ADMITTED_GLOBAL_STRATEGIES`, `execution/physical/_shadow_full_frame.py:119-121`; bucketize: no operator) | Arrow operator; top_code leaves `ADMITTED_GLOBAL_STRATEGIES` (a shrink) |
| Chunked | top_code: chunked pandas; bucketize: chunked pandas if the null-count gate (`execution/_planner.py:508-526`) admits, else full frame | Arrow operator where the table is native-admitted; the bucketize gate is unchanged |
| Sequential FK, non-key column | Python handler | unchanged (V2-LOG) |
| Out-of-core | bucketize refused (`out_of_core_row_error_strategy_unsupported`, `execution/out_of_core/_compat.py:71-83`); top_code not supported | unchanged (V2-LOG) |
| Full-frame pandas | handler | handler, with the B2 and B3 oracle fixes |
| `when:` on the column | handler | handler (declines `when_not_admitted`; `_when_admission.py:46` is not widened) |

Native admission is per table on main: a declined column sends its whole table to the oracle route, where the handler runs as today.

### FK shapes

- Either strategy on an FK key column: declines (the native routes admit no FK-edge table: `fk_relationship_not_native_route`).
- Non-key column of an FK table: sequential route, handler, unchanged.

### Fields

- bucketize: `width` and `preset` (through `resolve_bucketize_width`), `format` (unknown becomes `lower`, as the oracle does). Declines: unresolvable width; integer width at or above 2**53; `declared_integer_output` true (V2-LOG).
- top_code: `cap`, `over_label`, `floor`, `under_label`, `preset` (resolvers `execution/_strategies/_top_code.py:396`, `:424`). Declines: unresolvable top bound; a bottom bound the resolver rejects.
- All resolved once in the settings helpers; the operator reads no config key.

### Output surfaces

- Masked column values and type (section 3 items 2, 3).
- Row errors: `format_error`, bucketize only (exit 3).
- Warning `top_code_generalized`: unified, one per column with whole-column counts (the oracle's frame); chunked, per chunk as the oracle chunked leg emits it.
- Route evidence: `arrow_python` backend; declines carry `source_type_not_numeric` or the config reason; `no_native_kernel_or_pool` stops firing for these strategies.

### Codes

- New: `reasons.route.SOURCE_TYPE_NOT_NUMERIC` (`source_type_not_numeric`, "Source type not an admitted numeric type."), declared in `reasons/route/_added.py` with `since=` the next engine minor, and `RouteDeclineCode.SOURCE_TYPE_NOT_NUMERIC` in `native/_route_decline_codes.py`. The reason string is `{strategy}_source_type_not_numeric:{column}:{type}`. This is a reason-catalog entry; no allowlist, census or baseline holds reason counts.
- New row-error reason text `value is out of range under bucketize` (value-free), defined once in `kernel/_bucket.py` as `BUCKETIZE_RANGE_REASON` and read by the oracle handler and the registry.
- Config declines use free-form reason strings, as every `*_config_rejection` in `_operator_config_rejections.py` does.

## 5. Design

1. **Kernel module** `kernel/_bucket.py` (new, about 170 lines). Imports pyarrow, numpy and Python only; nothing from `decoy_engine.execution`.
   - `EXACT_INT_BOUND = 2**53`, `BUCKETIZE_RANGE_REASON`.
   - `bucketize_array(arr, width, fmt) -> (out: pa.StringArray, error_positions: tuple[int, ...])`: casts to float64 (`safe=False`), branches on `isinstance(width, int)`, computes `lf` with `pc.divide`, `pc.floor`, `pc.multiply`, applies the exit mask for an integer width (`~pc.is_finite(f) | pc.abs(f) >= 2**53`, nulls excluded), nulls the exit positions before any cast, then builds labels per section 4 with `add_checked` and `cast(safe=True)`.
   - `top_code_array(arr, cap, over_label, floor, under_label) -> (out, over_count, under_count)` per the rendering table.
   - `python_float_str(arr)`: Arrow's float-to-string cast gives the same shortest round-trip digits as Python; the function adds `.0` to a plain integral result, pads a one-digit exponent (`e-7` to `e-07`), maps `inf`, `-inf`, and sends any value outside the band P3 proves equal to Python `str()` one by one.
   - `int_width_out_of_range(values: np.ndarray) -> np.ndarray` (bool mask): the same predicate over numpy for the oracle handler, so the bound and the rule have one home.
2. **Settings helpers in the handler modules.** `_strategies/_bucketize.py` gains `bucketize_settings(cfg) -> BucketizeSettings | None` (resolved width, normalized format, `declared_integer_output`), and `run()` uses it, so handler and operator read config one way and `_bucketize.py` stays the only width-rule caller (width sentry allowlist and baseline unchanged). `_top_code.py` gains `top_code_settings(cfg) -> TopCodeSettings | None`: None when `_resolve_top_bound` returns None or `_resolve_bottom_bound` raises its `StrategyError` (caught by type, nothing logged, no value kept). It also gains `top_code_warnings(column, over_count, under_count) -> list[QualityWarning]`, which `run()` now uses, so the warning has one builder.
3. **Params and admission.** `native/_operator_params.py` gains `BucketizeParams(width, fmt)` and `TopCodeParams(cap, over_label, floor, under_label)`, built from the settings helpers once per column. `native/_operator_config_rejections.py` gains `bucketize_config_rejection` and `top_code_config_rejection` (settings None, integer width at or above 2**53, `declared_integer_output`), dispatched from `native/_plan.py:_config_rejection`. `native/_real_type_admission.py` gains `numeric_source_type_rejection(strategy, column, schema)`, reading the spec's `unified_resident_types`, coded `SOURCE_TYPE_NOT_NUMERIC`. `string_source_type_rejection` is not changed.
4. **Operator entries** in `native/_kernels_scalar.py`: `native_bucketize(source, params)` and `native_top_code(source, params)`, about 20 lines each. `native/_operator_step.py` dispatches both with one branch (`isinstance(params, (BucketizeParams, TopCodeParams))`), returning `StepResult` with `format_error_positions` and the top_code counts.
5. **Registry**: two `OperatorSpec`s, `planned_backend=ARROW_PYTHON`, `required_kernel=None`, `positive_kernel_evidence=False`, `unified_resident_types` = the admitted set (section 4), `full_frame_assembly="null_on_empty"`, `routed_diagnostics` = `{"reduce_row_error:format_error"}` for bucketize and `{"reduce_row_error:format_error", "reduce_warning:top_code_generalized"}` for top_code. `SLICE_STRATEGIES` is derived from `OPERATORS` (`physical/_shadow_bindings.py:73`), so it follows.
6. **Reason as a registry fact (H8).** `OperatorSpec` gains `format_error_reason: str | None = None`. bucket_perturb gets `transforms.bucket_perturb.FORMAT_ERROR_REASON`, date_shift its current text (moved from `_date_shift_ext.py:64` into the registry, and `_date_shift_ext.FORMAT_ERROR_REASON` re-exported from there), bucketize `BUCKETIZE_RANGE_REASON`. `format_error_reason(operator_id)` looks the spec up by id and raises `AssertionError` for an operator with no reason. `_chunk_masking.py:274-280` stores `format_errors[name] = (operator_id, positions)`; `format_error_records(table, errors_by_column)` takes that map; `_chunked_entry.py:344-350` passes it straight through and drops the `isinstance` set and its `BucketPerturbParams` import (net about minus 6 lines). Sequential (`_sequential_native_ops.py:491-492`) and shadow (`physical/_shadow_operators.py:429`) already pass an operator id and keep working.
7. **Degenerate chunk type.** `_chunk_masking.py:257` changes from `isinstance(params, BucketPerturbParams)` to "the column's spec has `full_frame_assembly == "null_on_empty"`", so bucket_perturb, bucketize and top_code share one rule.
8. **Unified warnings.** `_shadow_assembly.per_node_warnings` adds `top_code_node_warnings(binding, source, column)`, which runs the top_code count over the whole source column and calls `top_code_warnings`. Unified `format_error` rows follow the existing route: collected, rebased, handed to `finalize_validators_and_quarantine`, which reroutes the table to the oracle on a non-empty set.
9. **Capabilities**: `_capabilities.py:273-302` notes updated (top_code no longer "excluded for lack of a native kernel"); `row_error_modes` unchanged. The edit replaces text; the file stays at or under 600.
10. **Full-frame wrap**: `top_code` leaves `ADMITTED_GLOBAL_STRATEGIES` (`physical/_shadow_full_frame.py:119-121`); the comment is updated.
11. **Config-only and layering test** (P10): an AST test in `tests/unit/kernel/test_bucket_kernel.py` asserts `kernel/_bucket.py` calls no reduction (`min`, `max`, `quantile`, `mean`, `sum`, `pc.min_max`, `pc.quantile`, `.describe`, `np.percentile`, through attribute, name or `getattr` forms) and has no `import` or `from` of `decoy_engine.execution`. Not a registered sentry.
12. **Oracle fixes** (B2, B3) in `_strategies/_bucketize.py`: for an integer width, compute `bad = nums.notna() & int_width_out_of_range(nums.to_numpy(float64))`, append one `RowError(trigger="format_error", reason=BUCKETIZE_RANGE_REASON)` per bad row, and format only the good rows, so `astype("Int64")` never sees a bad value; bad rows keep the source value through the existing `where`. The file grows from 134 to about 150 lines.

Design notes: one arithmetic rule (float mirror) shared by construction, one bound and reason in the kernel module, one settings read per strategy, one registry fact per operator for reason, assembly, admitted types and diagnostics. No new `isinstance` scatter; one is removed in `_chunked_entry.py` and one generalized in `_chunk_masking.py`.

## 6. Slices and size

| Slice | Content | Files (lines at anchor, budget after) | Tests | Risk | Depends on |
|---|---|---|---|---|---|
| S1a (about 1 builder-day) | Kernel, oracle fixes, settings and warning helpers. No route change. | `kernel/_bucket.py` (new, about 170); `kernel/__init__.py` (exports); `execution/_strategies/_bucketize.py` (134, about 155); `execution/_strategies/_top_code.py` (466, about 490); `CHANGELOG.d` fragment; `docs/compatibility-contract.md` (B2, B3 wording) | P1, P2 (kernel and oracle cells), P3, P3b, P10; new `tests/unit/kernel/test_bucket_kernel.py`, `tests/unit/strategies/test_bucketize_range_exit.py` | R2 | E3 (merged) |
| S1b (about 1 builder-day) | Registry, admission, params, step, unified and chunked wiring, reason fact, warnings, docs | `execution/_operator_registry.py` (312, about 340); `native/_operator_params.py` (358, about 400); `native/_operator_config_rejections.py` (324, about 360); `native/_plan.py` (420, about 432); `native/_real_type_admission.py` (196, about 215); `native/_route_decline_codes.py` (124, 125); `reasons/route/_added.py` (76, about 82); `native/_kernels_scalar.py` (384, about 430); `native/_operator_step.py` (569, at most 580); `native/_chunk_masking.py` (447, about 450); `native/_chunked_row_errors.py` (44, about 44); `native/_chunked_entry.py` (688, about 682); `native/_date_shift_ext.py` (about 252, about 250); `physical/_shadow_assembly.py` (161, about 175); `physical/_shadow_full_frame.py` (comment and set); `native/_capabilities.py` (581, at most 590); `CODEMAP.md`; `docs/compatibility-contract.md` (route table); CHANGELOG fragment | P4, P5, P6, P8, P9; new `tests/parity/test_bucket_topcode_native.py`; flipped assertions in `tests/native/test_operator_registry.py` and any test expecting `no_native_kernel_or_pool` or the full-frame wrap for top_code | R2 | S1a |

`native/_requirements.py` (655, ceiling 677) is not edited: `native_kernel_rejection` returns None for `required_kernel=None` specs, as for truncate. Not edited either (entries already present): `_technique_class.py`, `native/_determinism_protocol.py`, `_chunked_fk_vocab.py`, `_column_access.py`, `native/_when_admission.py`, `physical/_shadow_bindings.py`, `physical/_shadow_operators.py` (the shadow binding reads params through the step; the builder confirms `_shadow_operators.py:174`'s params map needs no row, and adds one line if it does). No module crosses 600 lines and no census ceiling moves: `_chunked_entry.py` shrinks, `_operator_step.py` grows by at most 11.

Full-suite triggers: S1a changes an oracle byte rule (frozen contract); S1b flips existing assertions and moves gating. Each slice runs T3 on its merge head against the saved main baseline.

## 7. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `_bucket.py` | `src/decoy_engine/kernel/` | "Arrow kernels: `src/decoy_engine/kernel/`, by kernel operation" | `_scalar.py`, `_code_set.py` |
| `test_bucket_kernel.py` | `tests/unit/kernel/` | unit tests mirror `src/` | existing kernel tests |
| `test_bucketize_range_exit.py` | `tests/unit/strategies/` | strategy unit tests | `test_numeric_shape.py` |
| `test_bucket_topcode_native.py` | `tests/parity/` | cross-route parity | `test_chunked_substrate_parity.py` |

No new module under any package frozen by `tests/sentry/layout/test_package_fanout.py` (`execution` 103, `execution/native` 55, `execution/out_of_core` 44, `execution/_strategies` 28 all unchanged). CODEMAP's `kernel/` rows gain `bucketize_array`, `top_code_array`.

## 8. Class table (catalog `recurring-defects.md`)

| # | Class | Applies | Structure and proof | Mutation that must turn it red |
|---|---|---|---|---|
| 1 | Anchored validation | no: no text parsed | n/a | n/a |
| 2 | Strict wire and stored types | no persisted model | n/a | n/a |
| 3 | No exception context | `top_code_settings` catches one `StrategyError` type and returns None; nothing is logged or kept | P6 asserts the oracle's error text is unchanged | n/a |
| 4 | Versioned read models | no reader | n/a | n/a |
| 5 | Normalized guard scanners | P10 AST test | call nodes in attribute, name and `getattr` forms; import nodes | add `arr.max()` (red); add `getattr(pc, "quantile")` (red) |
| 6 | No reaching into private modules | operator calls handler helpers in the same package (precedent `_kernels_scalar.py:55`); the kernel imports nothing from `execution` | P10 import check (import-linter treats `execution` and `kernel` as siblings, so it cannot catch this) | add `from decoy_engine.execution import _row_errors` to `kernel/_bucket.py` (P10 red) |
| 7 | No hidden CI failures | none new | n/a | n/a |
| 8 | One input, one trust class per entry point | no new entry point | n/a | n/a |
| 9 | Mutations on the final head | named mutations rerun after the last change | gate record | n/a |
| 10 | Allowlisted helpers still checked | width sentry allowlist stays at four files | existing sentry unchanged | call `resolve_bucketize_width` from `_kernels_scalar.py` (width sentry red) |
| 11 | No raised caps | module-size ceilings, fan-out pins | none raised (section 6, 7) | n/a |

### Harness defect classes (`docs/handoffs/DEFECT-CATALOG.md`)

| # | Class | Where it applies | Closing structure | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | `format_error` reason, config decline strings | fixed reason text; decline strings carry column name and type only | P5 asserts reason text; existing value-free sentries | put the value in the reason (sentry red) |
| 2 | Cleanup missing on an exit path | out-of-range rows on chunked | the chunk fails before the offset advances, the vault is written or it yields (`_chunked_entry.py:351-380`, unchanged) | P5 chunked cell: no output file | yield before raising (P5 red) |
| 3 | State and concurrency | per-chunk invocation | pure kernel; params resolved once, immutable | P4 chunk-size sweep | cache params at module level keyed by column name (P4 two-config cell red) |
| 4 | Route parity and silent fallback | unified, chunked, full frame | one kernel; every decline coded | P4, P2 decline cells | admit `float32` (P2 float32 cell red) |
| 5 | Referential integrity | FK key columns | native routes admit no FK-edge table | P8 | n/a (existing gate) |
| 6 | Untrusted producer | source values | typed edge corpus through kernel and oracle | P2 | unchecked `add` with the exit check removed (P2 int64 max cell red) |
| 7 | Check then use | N/A: type check and arithmetic run over the same immutable Arrow array in one call | n/a | n/a | n/a |
| 8 | Weak tests | equality without types | P4 compares Arrow tables with schema, plus output hash | P4 | compare `to_pylist()` only (reviewer check) |
| 9 | Refactor drift | reason channel refactor, `_chunk_masking` rule | P5 per operator reason; existing date_shift and bucket_perturb chunked row-error tests stay green unchanged | P5, existing tests | map every operator to date_shift's reason (P5 red) |
| 10 | Frozen contract drift | B2, B3 text; route table | contract and fragment | docs review, P2 | n/a |

## 9. Acceptance tests (each fails before its slice unless marked)

- **P1 kernel units (S1a).** `bucketize_array` and `top_code_array` against hand-written expectations: every cell of both section 4 tables, every format, every preset, negative values (`-15` with width 10 gives `-20`, range `-20--11`), width 1, widths 3 and 2.5, hipaa_age, floor with under_label, floor without under_label (no under). Fail-before: module absent.
- **P2 typed edge corpus (S1a kernel and oracle; S1b route cells).** Kernel and oracle on the same values: nulls, `0`, `-0.0`, NaN, `inf`, `-inf`, `2**53 - 1`, `2**53`, `2**53 + 1`, `2**62 + 7`, int64 min, int64 max, int64 max `- w + 1`, `uint32` max, `1e19`, subnormals, `-1e300`, `-2.0**63`; integer width 10 and 7, float width 2.5, each format. Outputs and `(row, trigger, reason)` equal. Out-of-range cells give the exit in both. Decline cells (S1b): `float32`, `uint64`, `string`, `decimal128`, `bool` each decline with `source_type_not_numeric`, and the run's output equals main's. Fail-before: no kernel; the oracle crashes on int64 max, `1e19` and `inf`.
- **P3 float format property (S1a).** `python_float_str` equals `pd.Series(values).astype(str)` on 1,000,000 random doubles drawn across every binary exponent, plus `0.0`, `-0.0`, `inf`, `-inf`, subnormals, `2**53 ± 1`, `1e15`, `1e16`, `1e-4`, `1e-5`, `0.1 + 0.2`. Fail-before: function absent.
- **P3b float mirror property (S1a).** `bucketize_array`'s `lf` equals `np.floor(pd.to_numeric(s) / w) * w` bit for bit (NaN to NaN) for 400,000 random int64 (half full range, half within 2**53) and 600,000 random finite doubles (normal, uniform to `1e18`, raw bits), widths 1, 3, 7, 10, 1000, 2.5, 0.1. Then full labels equal the oracle handler on the in-range subset. Fail-before: module absent.
- **P4 route parity (S1b).** Each strategy; sources int64 without nulls, int64 with nulls and a value above 2**53, int32, uint32, float64 with NaN; 2,000 rows (unified) and 120,000 rows on chunked at chunk sizes 1,000, 7,919 and 50,000. Degenerate cells on every route: zero rows, all-null column, and (chunked, top_code) one all-null chunk. Asserts: the column's backend is `arrow_python`; the output equals forced full frame as an Arrow table, schema included, and by hash; on chunked it also equals the oracle chunked leg chunk by chunk (type per chunk); warnings equal (code, column, counts) to forced full frame on unified and to the oracle chunked leg on chunked. bucketize on chunked uses null-free sources (the gate holds); a null-bearing bucketize table on chunked asserts the planner still sends it whole-frame. F06 cell: a text column declared as integer under top_code is admitted on unified (post-cast, `_pipeline_full_frame.py:164-167`) and declines on chunked with `source_type_not_numeric`; output equals forced full frame on both. A two-config cell (two bucketize columns, widths 10 and 7). Fail-before: full frame or chunked pandas.
- **P5 row errors (S1b).** A float64 column with 1% `inf` and one `1e19` under bucketize with width 10. Full frame and unified: records equal (table, column, row index, trigger `format_error`, reason `value is out of range under bucketize`); under `row_errors: quarantine` the rows go to the quarantine file and the main output equals full frame; under `fail` the job fails identically. Chunked: the job fails with `RowErrorsFailedError`, `row_index` chunk-local, records equal to the oracle chunked leg, no output file. A date_shift and a bucket_perturb chunked cell keep their own reason text. Fail-before: the oracle crashes with `OverflowError`.
- **P6 config declines (S1b).** bucketize with an unresolvable width, an integer width of 2**53, and `declared_integer_output`; top_code with `floor` but no `under_label`, and an unusable cap: each declines at admission with its config reason, and the run then behaves exactly as main (the same `StrategyError` code and text, or the same output for `declared_integer_output`). Unchanged-behavior control.
- **P8 unchanged routes (S1b, control).** Sequential FK job with both strategies on non-key child columns, and an out-of-core job with top_code: route and output equal main.
- **P9 HIPAA column (S1b).** The hipaa template's top_code column config, inlined in the engine test (`strategy: top_code`, `preset: hipaa_age`) on a typed int64 source at 120,000 rows, chunked and unified: backend `arrow_python`, output equals forced full frame. Fail-before: pandas.
- **P10 config-only and layering test (S1a).** Passes on `kernel/_bucket.py`; fails on its seeded reduction and import cases. `tests/sentry/test_bucketize_width_contract.py` passes with its baseline unchanged.

Named mutations (record the head): drop the 2**53 exit (P2 `2**53 + 1` cell red: oracle exits, kernel labels); unchecked `add` with the exit removed (P2 int64 max cell red); branch on source dtype instead of width type (P1 float-source int-width cell red: `20.0` against `20`); drop the `.0` suffix rule (P3 red); admit `float32` (P2 decline cell red); drop the `null_on_empty` chunk rule for top_code (P4 all-null chunk type red); map bucketize to date_shift's reason (P5 red); call `resolve_bucketize_width` from `_kernels_scalar.py` (width sentry red); import `execution` from the kernel (P10 red).

Performance evidence (performance.md): the section 1 probe rerun through the real operator at 120,000 and 1,000,000 rows, three runs each on the Dell node, wall time and peak RSS, before and after, in the S1b PR body.

## 10. Frozen contracts and byte changes

Named changes (fragment and contract), all bucketize with an integer width; float widths and top_code are byte-identical to main:

1. **B2 out-of-range magnitude.** A non-null value whose float64 magnitude is at or above 2**53 gives a `format_error` row error (`value is out of range under bucketize`) and is quarantined or fails the job per policy. Before: a label computed from a rounded float (`2**53 + 1` gave `9007199254740990`; `-2**63` gave `-9223372036854775808`), or an uncoded `TypeError` crash (`2**63 - 1`, `1e19`).
2. **B3 non-finite float.** `inf` or `-inf` gives the same `format_error`. Before: an uncoded `OverflowError` crash.

Dropped from revision 2: B1 (type pin; the oracle's degenerate types are kept), old B2 (exact large integers; replaced by the exit), B4 (chunked gate removal; the gate stays).

Fragment first line: `Breaking: bucketize with an integer width now reports a format_error row for an infinite value or a value at or above 2**53 in magnitude, instead of crashing or labelling a rounded value; bucketize and top_code run a vectorized Arrow operator on the unified and chunked routes.`

Contract: `docs/compatibility-contract.md` bucketize paragraph (B2, B3), the route table rows for both strategies (unified and chunked: Arrow operator; sequential and out-of-core unchanged), and one sentence that the operator declines every input E3 refuses plus `float32` and `uint64`. `SEED_PROTOCOL_VERSION`, plan serialization and digests do not change (neither strategy is keyed). No public signature changes.

## 11. Pre-mortem

- Arrow and Python disagree on some float digits. P3 covers every exponent band; a value outside the proven band goes through `str()`, so the worst case is speed, not bytes.
- The float mirror drifts with a pyarrow upgrade. P3b is the guard. CI runs the locked pyarrow (24.0.0 in `uv.lock`); the builder records the version in the PR.
- top_code's chunked oracle leg renders a null-bearing large int64 through float64 (if the chunk lane does not use the lossless ingest). P4's int64-with-nulls-above-2**53 cell compares the native leg against the oracle chunked leg; if they differ, the existing integer-column chunk gate (`_chunked_input.py:161-181`) is the explanation to confirm, and the builder reports it before changing anything.
- #790 (date_shift native) edits `_date_shift_ext.py` near the reason text. Whichever lands second moves the reason into the registry field; the builder rereads the file at S1b start.
- E5 edits the same contract and CODEMAP text. Merge, do not rewrite.

## 12. Owner questions

None. Revision 3 adds no allowlist, census, fan-out or baseline entry and raises no module-size ceiling. The one new reason code is a catalog entry.

## 13. Deferred (V2-LOG)

- **V2-LOG: sequential route** (non-key columns of FK tables). Reason: no generic seam yet; the descriptor module would grow the frozen `execution` fan-out or `_sequential_native.py` (700 of 700). Revisit after `execution/sequential/` exists and `SeqNativeRun.native_column` takes generic operators with zero net lines.
- **V2-LOG: out-of-core route.** Reason: no row-error channel on that route (`out_of_core/_compat.py:71-83`); bucketize's exit would need a fail-closed path there. top_code alone could run, but it needs a new stream module under a frozen package.
- **V2-LOG: removing the bucketize chunked null-count gate**, with a `_chunked_schema_rule.py` pin on both legs. Reason: the pandas chunked leg's type depends on chunk content while admission is per table.
- **V2-LOG: `float32` sources.** Reason: the oracle computes and prints in float32 (`2.6`, not `2.5999999046325684`); needs a float32 formatter and its own property test.
- **V2-LOG: `uint64` sources**, **`decimal128`** (E3 admits bucketize on precision 15 or less), **`bool`**.
- **V2-LOG: `declared_integer_output`** on the operator. Reason: the oracle's output type there (`Int64` mixed with kept source values) needs its own type proof.
- **V2-LOG: `top_code_generalized` counts summed across chunks** (with the shared chunked-evidence fix).
- **V2-LOG: `when:` on either strategy.**
