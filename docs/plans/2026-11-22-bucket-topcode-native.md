Status: plan (revision 2, 2026-11-24; re-anchored to cb06f318e)

# BUCKET-TOPCODE-NATIVE: vectorized Arrow operators for `bucketize` and `top_code`

Owner: Cam. Author: Opus (plan author). First written 2026-11-22. Roadmap row: BUCKET-TOPCODE-NATIVE (group mask; V1 fast-path audit, vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`). Engine only. The CLI gets it through its next engine pin bump.

Anchors: a path with no prefix is under `src/decoy_engine/`. Read at engine `origin/main` `cb06f318e`. Must stay consistent with `plan/route-label-truth` (an Arrow backend is not "native_executed"), `plan/per-column-routing` (each column takes its own route), `plan/native-threads-default`, `plan/when-reads-source` and `docs/plans/2026-11-21-column-shape-rule.md` (COLUMN-SHAPE-RULE).

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `profiles/local-operations.md`, `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md`.

Risk: R2 (two anonymisation strategies used by the HIPAA template move off pandas on four routes; named byte changes, two of them bug fixes in the oracle). Plan review: Dennis, then Codex. Code gate: Codex; Dennis on S1.

Owner direction (2026-11-22): every strategy runs its fastest path by default; pandas only where no faster build exists, named on the run card and in the docs; faster and more robust wins even when bytes change, and every byte change is named; output stays deterministic per seed. Engine-gap deadline 2026-12-15.

## 0. Revision 2 changes (re-anchor to `cb06f318e`)

Revision 1 was read at `70881ad79`. Since then COLUMN-SHAPE E3 (#753) and E2 (#762) merged, with #770 (UF-DOMAIN, untouched columns written from the source on pandas routes). What changed in this plan:

- **Source domain narrowed by E3.** Compile now refuses `bucketize` and `top_code` on a text column with no F06 `logical_type` declaration (`plan/column_shape_required`), and the handlers refuse at runtime a column the plan does not list as typed (`runtime/column_shape_required`, `execution/_adapter.py:346-363`). A declared text column is cast by the F06 boundary before masking. So undeclared text never reaches either strategy on a compiled run. The revision 1 string parse (regex fast path plus `pd.to_numeric` residue) is dropped: the operator takes typed numeric arrays only, and any string or object input declines to the handler, which owns the shape refusal. The kernel shrinks from about 260 to about 150 lines.
- **Width read through the one width rule.** `BucketizeStrategyHandler._resolve_width` no longer exists. `contracts/bucketize_width.py` (`resolve_bucketize_width`) is the one rule, and `tests/sentry/test_bucketize_width_contract.py` pins its four callers. The operator must not become a fifth caller, because that grows the sentry's allowlist and baseline. Design: `_strategies/_bucketize.py`, already an allowed caller, gains `bucketize_settings(cfg)`, which the operator imports (section 5 item 2).
- **Statistic sentry redesigned.** Revision 1 added a registered sentry and a `scripts/dev/sentry_registry.toml` row. That grows the sentry list. It becomes an AST test inside the kernel unit tests, on the one module that holds the arithmetic (section 5 item 7). No owner question needed.
- **`top_code` whole-column failure no longer reachable from the operator.** `top_code_non_integral_object_column` needs an object (text or Decimal) column. E3 refuses text without a declaration and refuses a decimal under `top_code` (`plan/column_shape_mismatch`). The operator never sees one; the handler keeps its object path. Revision 1's P6 is replaced.
- **`bucketize` on a decimal.** E3 admits a decimal of precision 15 or less with a whole-number width on the handler. The operator declines `decimal128` to the handler (deferred, section 13).
- **Row errors.** With text gone, the only `format_error` source left for the operator is a non-finite float (B3).
- **File sizes.** `execution/native/_chunked_entry.py` is 688 lines (700 hard maximum); S1 adds nothing there. `_sequential_native_ops.py` (593), `out_of_core/_hash_run.py` (589) and `out_of_core/_mask_group_c.py` (544) cannot take S2's additions; S2 adds sibling modules.
- **All line citations** updated to `cb06f318e`.

No merged engine PR already does this work (searched merged PRs for "bucketize native" and "top_code native"). #790 (open, `date_shift` native on typed `date32`) is the nearest sibling and does not touch these strategies.

COLUMN-SHAPE slices still open: E0b (date strategies), E5 (starter, scan, `StrategyInfo.shape`, engine docs), C1, C2, C3 (CLI and language). None of them changes `bucketize` or `top_code` arithmetic or shape rules, so S1 does not wait for them. E5 edits `docs/compatibility-contract.md`, `CODEMAP.md` and the CHANGELOG; whichever lands second merges its doc text, it does not rewrite it.

Public signatures (#763 signature sentry): S1 and S2 change no public signature. The new functions are in `kernel/` and private `execution/` modules. The Breaking fragment in section 10 is for the output changes, not a signature.

## 1. Frame

`bucketize` and `top_code` have no entry in the operator registry (`execution/_operator_registry.py:131-312` lists passthrough, redact, truncate, text_redact, text_mask, hash, faker, categorical, bucket_perturb, group_key, date_shift, fpe). Today:

- `top_code` is row-local and CHUNK_SAFE, but excluded from the native route for lack of a kernel (`execution/native/_capabilities.py:281-302`); the unified slice sends it to full frame (`execution/physical/_shadow_full_frame.py:115-120`).
- `bucketize` runs chunked pandas only when the source is null-free numeric, because its output type depends on chunk content (`execution/_chunked.py:21-33`; gate at `execution/_planner.py:496-526`, columns from `execution/_planner_columns.py:20`, null-count facts at `execution/_chunked_input.py:161-212`). A column with nulls runs full frame.

Since E3, both strategies read only typed numbers: a typed integer or float column, a declared (F06) text column cast to an integer before masking, and for `bucketize` a decimal of precision 15 or less (`contracts/strategy_requirements.py:198-232`). Both are pure functions of the row's own value and config literals: the bucketize width from `width` or a preset through `contracts/bucketize_width.py` (`_bucketize.py:74-89`); the top_code `cap`, `over_label`, `floor`, `under_label` from config or the `hipaa_age` preset (`_top_code.py:396-460`). There is no percentile or column statistic, so "global statistics fixed in the config" already holds: no threshold is ever derived from data. This plan keeps it that way and makes a test of it.

Oracle semantics on typed input:

- bucketize (`_bucketize.py:66-134`): `pd.to_numeric(errors="coerce")`; `floor(v / width) * width`; an int width casts through `Int64`; formats `lower`, `range` (`lower-upper`, upper inclusive for int widths), `midpoint`; an unknown format silently becomes `lower` (`:87-89`); `declared_integer_output` keeps `lower` as an integer (`:114`); null stays null.
- top_code (`_top_code.py:148-268`): bounds must be finite with magnitude below 2**53 (`:72-100`); a numeric column uses `pd.to_numeric`; over the cap gives `over_label`, under the floor gives `under_label`, in range gives a canonical string (`"67"`, never `"67.0"`); a `top_code_generalized` warning carries chunk-local counts.

### Measurement (decides Rust against Arrow)

Probe on the Dell node through `vm-run`, 1,000,000 rows, minimum of five runs (pyarrow 24.0.0, pandas 2.3.3):

| Case | pandas oracle logic | Arrow compute | Ratio |
|---|---|---|---|
| bucketize int64 with 1% nulls, width 10, `range` | 783 ms | 82 ms | 9.5x |
| bucketize float64, width 2.5, `range` | 2,065 ms | not run (format question below) | |
| top_code int64 with nulls, cap 89 | 1,009 ms | 48 ms | 21x |
| top_code int64 no nulls | 328 ms | | |
| Parquet write and read, int64 column | 23 ms | | |
| Parquet write and read, bucket label strings | 149 ms | | |

Revision 1 also measured a string source; E3 removed that input. Arrow output equals the oracle for int bucketize (`range`, negative values included: `-20--11`) and int top_code. Arrow compute is 48 to 82 ns per row; writing and reading the label column alone is about 149 ns per row. A Rust kernel could save at most the 50 to 80 ns per row of compute, below the I/O floor and inside run-to-run noise end to end. Decision: **a vectorized Arrow operator (`ARROW_PYTHON`, `required_kernel=None`), no Rust.** This matches how redact, truncate and text_redact already run (`execution/_operator_registry.py:142-171`).

The probe also found three facts the design must handle:

1. Arrow formats floats differently: Python and pandas give `20.0`, `-0.0`, `1e-07`; `pc.cast(float64 -> string)` gives `20`, `-0`, `1e-7`.
2. `pc.cast(int64 -> float64)` raises `ArrowInvalid` above 2**53, and the oracle silently loses precision there: both `2**53 + 1` and `9_007_199_254_740_993` bucket to `9007199254740990`.
3. The oracle crashes on infinity: a float source value `inf` raises `OverflowError` out of bucketize's `Int64` cast instead of a coded error.

## 2. Established solutions

Search run: how columnar engines implement fixed-width binning and top-coding (Arrow compute `floor`, `divide`, `if_else`; DuckDB and Polars `cut`/`floor` expressions; sdcMicro `globalRecode` and `topBotCoding`; ARX generalization hierarchies; HIPAA Safe Harbor age rule 164.514(b)(2)(i)(C)).

- Fixed-width recoding is `floor(x / w) * w` everywhere (sdcMicro `globalRecode` with equal breaks, Polars `floor`); top-coding is a threshold compare with a replacement label (sdcMicro `topBotCoding`). Nothing to invent.
- Parsing text into numbers is now the F06 boundary's job (`declared_casting/_boundary.py`), not the strategy's. The operator reads the cast array.

### Reuse inventory

- `kernel/` package, "Arrow kernels" row in CODEMAP (`CODEMAP.md:277`, "by kernel operation"; package row at `:122`): the new array functions go here beside `redact_array` and `truncate_array` (`kernel/_scalar.py`).
- `execution/native/_kernels_scalar.py` (384 lines): the existing home of `native_redact`, `native_truncate`; the two operator entries join it. It already imports a handler helper (`:55`, `_text_redact._splice`), the precedent for item 2 in section 5.
- `OperatorSpec.routed_diagnostics` with `reduce_row_error:format_error`, as bucket_perturb and date_shift do (`execution/_operator_registry.py:254`, `:275`), and `reduce_warning:<code>` as text_mask and fpe do.
- The chunked format-error channel (`execution/native/_chunked_entry.py:300-350`, `_chunked_row_errors.format_error_records`), reused unchanged.
- The one width rule `contracts/bucketize_width.resolve_bucketize_width`, reached through the handler module; the top_code resolvers `TopCodeStrategyHandler._resolve_top_bound` and `_resolve_bottom_bound` (`_top_code.py:396`, `:424`): called, not copied, so a preset or bound rule has one owner.
- `execution/native/_operator_config_rejections.py`: the home for the config-level declines.

## 3. Guarantee and non-goals

After S2:

1. A `bucketize` or `top_code` column whose source arrives as `int8`-`int64`, `uint8`-`uint32`, `float32` or `float64` (typed, or an F06 integer declaration after its cast), with no `when:`, runs the Arrow operator on unified slice, chunked, sequential (non-key) and out-of-core, at any row count.
2. Output equals the oracle row for row on every admitted route, except the named changes in section 10, which are made in the oracle too, so oracle and operator agree.
3. Chunk-stable: the output type and every value depend only on the row's value and the config. A column's output type is `string` on every route and every chunk (`int64` for bucketize `lower` with `declared_integer_output` and an int width), whatever the chunk's null content.
4. Thresholds and widths are config literals or presets only. A test fails if the kernel module reads a column statistic.
5. Row errors (`format_error`, only from a non-finite float under bucketize) match the oracle by row and code.
6. Any other input (string, large_string, object, `decimal128`, bool, `uint64`) declines to the handler before masking, and the handler applies the E3 shape rule. The operator never decides a shape question.

Non-goals: Rust; quantile or data-derived bins (none exist); new formats or presets; any text parsing (F06 owns it); making `top_code_generalized` counts global on the chunked route (known limitation, `docs/backlog/chunked-audit-evidence-row-indices.md`; counts stay per chunk as today); `decimal128` and bool sources (decline, section 4); FK key columns (decline).

## 4. Enumerations

### Exit paths (per value)

1. null: null, no error.
2. finite integer: bucketed with integer arithmetic, or top-coded.
3. finite float: bucketed with float arithmetic, or top-coded.
4. float NaN: null in pandas, stays null.
5. float `inf` or `-inf`: bucketize gives `format_error` and keeps the value (was an `OverflowError` crash, B3); top_code compares as today (`inf > cap` is over the cap).
6. config invalid (unresolvable width, unusable bound, missing `under_label` with `floor`): the handler's existing `StrategyError` at preflight (`_bucketize.py:75-86`; `_top_code.py:364-460`), before any chunk, on every route. The settings helper returns None for these, and the operator declines so the handler raises.

### Inputs per array type

| Arriving array type | Operator | Why |
|---|---|---|
| `int8`-`int64`, `uint8`-`uint32` | admitted, integer path | exact in `int64` |
| `uint64` | declines | values above 2**63 do not fit the `int64` path |
| `float32`, `float64` | admitted, float path | |
| `string`, `large_string`, object | declines to the handler | E3: an undeclared column is refused there; parsing is F06's job |
| `decimal128` | declines (bucketize admitted by E3 on the handler) | deferred, section 13 |
| `bool`, any other | declines | E3 refuses it as a mismatch at compile |

### Routes

| Route | Today | After |
|---|---|---|
| Unified slice | full frame (no operator) | Arrow operator |
| Chunked | bucketize: chunked pandas if null-free numeric, else full frame; top_code: chunked pandas | Arrow operator, no null-count gate |
| Sequential FK, non-key column | Python handler | Arrow operator |
| Out-of-core | Python handler per batch | Arrow operator per batch |
| Full-frame pandas | handler | handler, with the oracle fixes in section 10 |
| `when:` on the column | handler | handler (declines `when_not_admitted`, per `plan/when-reads-source`) |

### FK shapes

- Either strategy on an FK key column (parent, child, composite part): declines to the Python handler; the FK gate admits only self-masking keys.
- On a non-key column of an FK table: Arrow operator on sequential and out-of-core.

### Fields

- bucketize: `width`, `preset` (through `resolve_bucketize_width`), `format`, `declared_integer_output` (`_bucketize.py:74-114`).
- top_code: `cap`, `over_label`, `floor`, `under_label`, `preset`.
- All resolved in the handler modules; the operator takes the resolved values and reads no config key itself.

### Output surfaces

- Masked column values and type (section 3 item 3).
- Row errors: `format_error` per row (bucketize, non-finite float).
- Warning `top_code_generalized` with `over_count`, `under_count` (per chunk on the chunked route, as today).
- Route evidence: `arrow_python` backend for the column; the decline `no_native_kernel_or_pool` stops firing for these strategies.

### Codes

No new reason code. A source type outside the domain declines with the existing source-type family: `string_source_type_rejection` (`execution/native/_real_type_admission.py:93-102`) takes exactly `string` today; S1 generalizes it to read the spec's `unified_resident_types`, keeping its reason text for the string strategies. `reasons.route.NO_NATIVE_KERNEL_OR_POOL` (`reasons/route/_part1.py:139`) stays registered for other strategies.

## 5. Design

1. **Kernel module** `kernel/_bucket.py` (new, about 150 lines): `bucketize_array(arr, width, fmt, declared_integer) -> (out, error_positions)`, `top_code_array(arr, cap, over_label, floor, under_label) -> (out, over_count, under_count)`, `python_float_str(arr)`.
   - Integer arrays use integer arithmetic: `lower = x - ((x % w) + w) % w` in `int64` via `pc.subtract`, `pc.add` and a floored modulo built from `pc.divide` on integers (Arrow integer division truncates toward zero, so the remainder is corrected for negatives). No float cast, so values above 2**53 stay exact.
   - Float arrays use `pc.floor(pc.divide(x, w)) * w` in float64, as the oracle does; non-finite positions are collected as `error_positions` and keep their value.
   - String output: integer labels via `pc.cast(int64 -> string)` (proven equal to pandas). Float labels via `python_float_str(arr)`: Arrow's cast gives the same shortest round-trip digits as Python's `repr`, so the formatter adds `.0` to a plain integral result, pads a one-digit exponent (`e-7` to `e-07`), and sends any value outside the band where both forms are proven equal to Python `str()` one by one. P3 is the property test that proves the band.
   - The module imports nothing from `execution` (import-linter: `kernel` is below `execution`).
2. **Settings helpers in the handler modules.** `_strategies/_bucketize.py` gains `bucketize_settings(cfg) -> BucketizeSettings | None` (resolved width, normalized format, `declared_integer_output`), and `run()` uses it too, so the handler and the operator read config one way. It calls `resolve_bucketize_width`, so `_bucketize.py` stays the allowed caller and the width sentry's allowlist and baseline do not change. `_top_code.py` gains `top_code_settings(cfg)` over `_resolve_top_bound` and `_resolve_bottom_bound`. Neither the operator nor the kernel reads `preset` or `width`, so the width sentry's other-key-read list does not change either. This is the choke point: the width sentry fails if `_kernels_scalar.py` calls the resolver or reads either key.
3. **Operator entries** in `execution/native/_kernels_scalar.py`: `native_bucketize`, `native_top_code`, about 30 lines each: call the settings helper, decline on None, call the kernel, return values plus error positions and warning counts.
4. **Registry**: two `OperatorSpec`s, `planned_backend=ARROW_PYTHON`, `required_kernel=None`, `positive_kernel_evidence=False`, `unified_resident_types` = the admitted types in section 4, `full_frame_assembly="type_preserving"`, `routed_diagnostics={"reduce_row_error:format_error"}` for bucketize and `{"reduce_warning:top_code_generalized"}` for top_code.
5. **Capabilities**: `_capabilities.py:273-302` notes updated; top_code no longer "excluded for lack of a native kernel". The file is 581 lines; the edit replaces text and must not grow it past 600.
6. **Chunked gate removal**: the bucketize null-count gate (`execution/_planner.py:496-526`, `_planner_columns._bucketize_columns`, `execution/_chunked_input.py:161-212`) exists only because the pandas output type depended on chunk content. With the type pinned it goes. The `_chunked.py:21-33` docstring is rewritten.
7. **Config-only test**: an AST test in `tests/unit/kernel/test_bucket_kernel.py` asserts that `kernel/_bucket.py` calls no reduction (`min`, `max`, `quantile`, `mean`, `pc.min_max`, `pc.quantile`, `.describe`, `np.percentile`, through attribute, name or `getattr` forms). The kernel takes the bounds as scalar arguments, so the arithmetic has no other place to get a threshold. Not a registered sentry, so no registry row.
8. **Oracle fixes** (section 10 B2, B3): the bucketize handler calls `kernel/_bucket.py`'s integer floor for integer dtypes and maps non-finite floats to `format_error`. The handler keeps its pandas frame plumbing; the arithmetic for these cases has one implementation.

Design notes: one settings read per strategy, one arithmetic implementation, one registry fact per operator, no text parse anywhere in this row. Per-column routing (`plan/per-column-routing`) lets a bucketize column run the Arrow operator while a sibling column stays on Python.

## 6. Slices and size

| Slice | Content | Files | Lines (estimate) | Risk | Depends on |
|---|---|---|---|---|---|
| S1 (about 1 builder-day) | `kernel/_bucket.py`, settings helpers, two operator entries, two specs, unified slice and chunked admission, oracle fixes B2 and B3, removal of the bucketize null-count gate, config-only test, contract text, changelog | `kernel/_bucket.py`, `kernel/__init__.py`, `execution/native/_kernels_scalar.py`, `execution/_operator_registry.py`, `execution/native/_capabilities.py`, `execution/native/_real_type_admission.py`, `execution/native/_operator_config_rejections.py`, `execution/_strategies/_bucketize.py`, `execution/_strategies/_top_code.py`, `execution/_planner.py`, `execution/_planner_columns.py`, `execution/_chunked_input.py`, `execution/_chunked.py`, `execution/physical/_shadow_full_frame.py:115-120`, docs, tests | source about 320, tests about 380 | R2 | E3 (merged) |
| S2 (about 0.5 builder-day) | Sequential and out-of-core: the two strategies as sequential `NativeOp` descriptors and in the out-of-core column gate, following bucket_perturb | new `execution/_sequential_native_numeric.py` (registered from `_sequential_native_ops.py`), new `execution/out_of_core/_mask_numeric.py` (beside `_mask_group_c.py`), small edits in `_sequential_native_ops.py` and `out_of_core/_hash_run.py`, tests | source about 90, tests about 200 | R2 | S1 |

File sizes at `cb06f318e`: `_sequential_native_ops.py` 593, `out_of_core/_hash_run.py` 589, `out_of_core/_mask_group_c.py` 544, `native/_chunked_entry.py` 688, `_planner.py` 591, `_chunked_input.py` 513, `native/_capabilities.py` 581. S2's sibling modules keep each existing file under 600; no ceiling is raised. S1 adds nothing to `_chunked_entry.py`; the gate removal shrinks `_planner.py` and `_chunked_input.py`.

Existing tests whose assertions flip (listed in the builder report): planner tests that expect the bucketize null-count gate (`grep -rn "bucketize" tests/unit/execution/test_planner*.py tests/native`), any test that expects `no_native_kernel_or_pool` for these strategies, and oracle tests that pin the old precision loss or the infinity crash (none found by `grep -rn "OverflowError" tests | grep -i bucket`; the builder confirms). E3's `tests/unit/strategies/test_numeric_shape.py` must stay green unchanged: the operator does not move the shape refusal. Changed assertions and moved gating are full-suite triggers, so S1 runs T3 on the merge head.

## 7. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `_bucket.py` | `src/decoy_engine/kernel/` | "Arrow kernels: `src/decoy_engine/kernel/`, by kernel operation" | `_scalar.py`, `_code_set.py` |
| `_sequential_native_numeric.py` | `src/decoy_engine/execution/` | sequential native ops | `_sequential_native_ops.py` |
| `_mask_numeric.py` | `src/decoy_engine/execution/out_of_core/` | out-of-core mask groups | `_mask_group_c.py` |
| `test_bucket_kernel.py` | `tests/unit/kernel/` | unit tests mirror `src/` | existing kernel tests |
| `test_bucket_topcode_native.py` | `tests/parity/` | cross-route parity | `test_chunked_substrate_parity.py` |

CODEMAP's `kernel/` rows (`CODEMAP.md:122`, `:227`) gain `bucketize_array`, `top_code_array`. The builder checks the `execution/` fan-out at S2 start; if `execution/` is over the limit, the sequential sibling goes under the package the CODEMAP names instead.

## 8. Class table (catalog `recurring-defects.md`)

| # | Class | Applies | Structure and proof | Mutation that must turn it red |
|---|---|---|---|---|
| 1 | Anchored validation | no: no text is parsed in this row (revision 1's regexes are gone) | n/a | n/a |
| 2 | Strict wire and stored types | no persisted model | n/a | n/a |
| 3 | No exception context | the settings helpers return None; the handler raises its existing value-free `StrategyError` | existing value-free sentries | n/a |
| 4 | Versioned read models | no reader | n/a | n/a |
| 5 | Normalized guard scanners | config-only test | AST walk over call nodes, attribute, name and `getattr` forms | add `arr.max()` to `kernel/_bucket.py` (red); add `getattr(pc, "quantile")` (red) |
| 6 | No reaching into private modules | operator calls handler settings helpers | same package (`execution`), precedent `_kernels_scalar.py:55`; the kernel imports nothing from `execution` | import a handler from `kernel/_bucket.py` (import-linter red) |
| 7 | No hidden CI failures | none new | n/a | n/a |
| 8 | One input, one trust class per entry point | no new entry point | n/a | n/a |
| 9 | Mutations on the final head | named mutations below rerun after the last change | gate record | n/a |
| 10 | Allowlisted helpers still checked | the width sentry's allowlist stays at four files | the existing sentry runs unchanged | call `resolve_bucketize_width` from `_kernels_scalar.py` (width sentry red) |
| 11 | No raised caps | module-size ceilings | no ceiling raised; S2 adds siblings | n/a |

### Harness defect classes (`docs/handoffs/DEFECT-CATALOG.md`)

| # | Class | Where it applies | Closing structure | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | `format_error` reasons | fixed reason text, never the value | existing value-free sentries, P5 asserts text | put the value in the reason (sentry red) |
| 2 | Cleanup missing on an exit path | config error after admission | settings resolve at preflight, before any chunk is written | P6 | resolve settings per chunk (P6 red) |
| 3 | State and concurrency | per-chunk invocation | the kernel is a pure function of array and resolved settings; no module state | P4 chunk-size sweep | cache settings at module level keyed by column name (P4 two-config cell red) |
| 4 | Route parity and silent fallback | five routes | one kernel; parity per route; any non-numeric input declines to the handler | P4, P7 | admit `string` and cast it (P2 string-decline cell red) |
| 5 | Referential integrity | FK key columns | decline on key columns | P8 | admit on a key (P8 red) |
| 6 | Untrusted producer | source values | typed edge corpus P2 through kernel and oracle | P2 | float cast for int sources (P2 large-integer cell red) |
| 7 | Check then use | N/A: the type check and the arithmetic run over the same immutable Arrow array in one call | n/a | n/a | n/a |
| 8 | Weak tests | equality without types | P4 compares Arrow tables with schema and output hash | P4 | compare `to_pylist()` only (reviewer check) |
| 9 | Refactor drift | removing the bucketize null-count gate | flipped planner tests listed; P4 proves the gate is no longer needed | P4 null-heavy chunk cells | restore the pandas route for one chunk (P4 type cell red) |
| 10 | Frozen contract drift | contract text on chunked bucketize and top_code; B1-B4 | contract rewritten, Breaking fragment | docs review, P3, P5 | keep old "null-free numeric" wording (reviewer check) |

## 9. Acceptance tests (each fails before its slice unless marked)

- **P1 kernel units (S1).** `bucketize_array` and `top_code_array` against hand-written expectations for every format, every preset, negative values, width 1, widths 3 and 2.5, `declared_integer_output`, hipaa_age, floor with under_label. Fail-before: module absent.
- **P2 typed edge corpus (S1).** Kernel and oracle on the same typed values: nulls, `0`, `-0.0`, NaN, `inf`, `-inf`, `2**53 - 1`, `2**53 + 1`, `2**62 + 7`, int64 min and max, `uint32` max, `float32` values, subnormals. Output and `(row, code)` row errors equal, except the named B2 and B3 cells. Decline cells: a `string`, `large_string`, `decimal128`, `bool` and `uint64` column each decline to the handler, and the string cell then fails with `runtime/column_shape_required` when the plan lists the column as text, as on main. Fail-before: no kernel.
- **P3 float format property (S1).** `python_float_str` equals `[str(v) for v in values]` on 1,000,000 random doubles drawn across every binary exponent, plus `0.0`, `-0.0`, subnormals, `2**53 ± 1`, `1e15`, `1e16`, `1e-4`, `1e-5`, `0.1 + 0.2`. Fail-before: function absent.
- **P4 route parity (S1).** Each strategy, sources int64 (with and without nulls), float64, and an F06-declared integer text column; 2,000 rows (unified slice) and 120,000 rows at chunk sizes 1,000, 7,919 and 50,000, including a chunk that is all null: the column's route is `arrow_python`, the output equals forced full frame as an Arrow table (schema included) and by hash, and the output type is `string` in every chunk (or, for the declared column, the type the F06 post-mask format gives, identical on both routes). Fail-before: full frame, or chunked pandas with a chunk-dependent type.
- **P5 row errors (S1).** A float64 column with 1% `inf` values under bucketize: row errors equal the oracle's on full frame, unified slice and chunked (global row indices on chunked). Fail-before: the oracle crashes (B3) and there are no native row errors.
- **P6 config error before output (S1).** bucketize with an unresolvable width, and top_code with `floor` but no `under_label`, 120,000 rows chunked: the run fails with the handler's existing code before any chunk is written, and the sink leaves no output. Unchanged-behavior control on full frame.
- **P7 sequential and out-of-core (S2).** Two-table FK job, both strategies on non-key child columns: native route recorded, output equals forced full frame. Fail-before: Python handler.
- **P8 FK key (S2).** Either strategy on a key column declines to the handler. Unchanged-behavior control.
- **P9 HIPAA template (S1).** The CLI `hipaa` template's top_code column (age, `hipaa_age`) on a typed integer source at 120,000 rows runs `arrow_python`. Fail-before: pandas.
- **P10 config-only test (S1).** The AST test passes on `kernel/_bucket.py` and fails on its seeded cases. The existing `tests/sentry/test_bucketize_width_contract.py` passes with its baseline unchanged.

Named mutations (record the head): integer floor without the negative correction (P1 `-15` cell red); float cast for int sources (P2 large-integer cell red); drop the `.0` suffix rule in `python_float_str` (P3 red); admit `string` input (P2 decline cell red); emit `top_code_generalized` counts as zero (P4 warning cell red); restore the null-count gate (P4 route assertion red); call `resolve_bucketize_width` from `_kernels_scalar.py` (width sentry red).

Performance evidence (performance.md): the section 1 probe rerun through the real operator at 120,000 and 1,000,000 rows, three runs each on the Dell node, wall time and peak RSS, before and after, in the PR body.

## 10. Frozen contracts and byte changes

Named changes (fragment and contract):

1. **B1 type pin.** An empty or all-null bucketize or top_code column is typed `string` on every route (was the source type, for example `double` or `null`, on pandas). `declared_integer_output` columns are typed `int64`. An F06-declared column keeps the post-mask output rule E3 set (`plan/_checks_declared_casting.py`, `strategy_output_logical`).
2. **B2 exact large integers (oracle and operator).** Integer sources with magnitude above 2**53 bucket exactly, because the arithmetic stays in `int64`. Example, width 10: `4611686018427387911` (2**62 + 7) was labelled `4611686018427387904` through float rounding; it is now `4611686018427387910`. Values with magnitude at or below 2**53 are unchanged.
3. **B3 infinity (oracle and operator).** A float source value of `inf` or `-inf` under bucketize gives a `format_error` row error and keeps its value; before, the run crashed with an uncoded `OverflowError`. top_code over a float infinity is unchanged.
4. **B4 chunked gate.** bucketize columns with nulls now run chunked; before they ran whole-frame. Values are unchanged.

Fragment first line: `Breaking: bucketize and top_code now run a vectorized Arrow operator on every route; an empty or all-null output column is typed string, integers above 2**53 bucket exactly, and an infinite source value under bucketize is a format_error row instead of a crash.`

Contract: `docs/compatibility-contract.md` chunked-strategy paragraph (bucketize "null-free numeric" condition), the route table entries for both strategies, and one sentence after the E3 correction saying the operator declines every input E3 refuses. `SEED_PROTOCOL_VERSION`, plan serialization and digests do not change (neither strategy is keyed). No public signature changes, so the #763 signature sentry needs no signature Breaking line.

## 11. Pre-mortem

- Arrow and Python disagree on some float digits. P3 covers every exponent band; a value outside the proven band goes through `str()`, so the worst case is speed, not bytes.
- Arrow integer division and modulo semantics differ by version. The kernel uses only `pc.divide` on integers plus an explicit floored-remainder correction, and P1 runs negative cells; the CI pyarrow floor (`pyproject.toml`) is the version P1 runs on.
- A route feeds the operator a column the F06 boundary did not cast. The operator declines any string input, so the handler's E3 backstop refuses it, as on main. P2's decline cell proves it.
- Removing the bucketize null-count gate exposes a dtype hazard somewhere else in the chunked substrate. P4's all-null chunk and null-heavy cells cover it.
- E5 edits the same contract and CODEMAP text. Merge, do not rewrite; the builder rereads both files at S1 start.

## 12. Owner questions

None blocking. The Rust option is closed by the measurement; reopen only if a profile shows these operators above 20% of a real run. Revision 2 adds no allowlist, baseline, census or sentry-registry entry.

## 13. Deferred (V2-LOG)

- **V2-LOG:** `top_code_generalized` counts summed across chunks (with the shared chunked-evidence fix).
- **V2-LOG:** `decimal128` sources for bucketize on the operator (E3 admits them on the handler: precision 15 or less, whole-number width), and bool sources.
- **V2-LOG:** `uint64` sources above 2**63.
