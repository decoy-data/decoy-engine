Status: plan (revision 1, 2026-11-22)

# BUCKET-TOPCODE-NATIVE: vectorized Arrow operators for `bucketize` and `top_code`

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: BUCKET-TOPCODE-NATIVE (group mask; V1 fast-path audit, vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`). Engine only. The CLI gets it through its next engine pin bump.

Anchors: a path with no prefix is under `src/decoy_engine/`. Read at engine `origin/main` `70881ad79` (0.28.3). Must stay consistent with `plan/route-label-truth` (an Arrow backend is not "native_executed"), `plan/per-column-routing` (each column takes its own route), `plan/native-threads-default` and `plan/when-reads-source`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `profiles/local-operations.md`, `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md`.

Risk: R2 (two anonymisation strategies used by the HIPAA template move off pandas on four routes; named byte changes, two of them bug fixes in the oracle). Plan review: Dennis, then Codex. Code gate: Codex; Dennis on S1.

Owner direction (2026-11-22): every strategy runs its fastest path by default; pandas only where no faster build exists, named on the run card and in the docs; faster and more robust wins even when bytes change, and every byte change is named; output stays deterministic per seed. Engine-gap deadline 2026-12-15.

## 1. Frame

`bucketize` and `top_code` have no entry in the operator registry (`execution/_operator_registry.py:130-286` lists passthrough, redact, truncate, text_redact, text_mask, hash, faker, categorical, bucket_perturb, group_key, date_shift, fpe). Today:

- `top_code` is row-local and CHUNK_SAFE, but excluded from the native route for lack of a kernel (`execution/native/_capabilities.py:281-300`); the unified slice sends it to full frame (`execution/physical/_shadow_full_frame.py:115-120`).
- `bucketize` runs chunked pandas only when the source is null-free numeric, because its output type depends on chunk content (`execution/_chunked.py:21-33`, gate at `execution/_planner.py:442-490` and `execution/_chunked_input.py:163-205`). A string source runs full frame.

Both are pure functions of the row's own value and config literals: bucketize width from `width` or a preset (`execution/_strategies/_bucketize.py:51-59`, `:146-153`); top_code `cap`, `over_label`, `floor`, `under_label` from config or the `hipaa_age` preset (`execution/_strategies/_top_code.py:68`, `:394-460`). There is no percentile or column statistic, so "global statistics fixed in the config" already holds: no threshold is ever derived from data. This plan keeps it that way and makes a sentry of it.

Oracle semantics:

- bucketize (`_bucketize.py:95-143`): `pd.to_numeric(errors="coerce")`; `floor(v / width) * width`; an int width casts through `Int64`; formats `lower`, `range` (`lower-upper`, upper inclusive for int widths), `midpoint`; an unknown format silently becomes `lower` (`:96-98`); `declared_integer_output` keeps `lower` as an integer; a non-null value that does not coerce keeps its original text and adds a `format_error` row error; null stays null.
- top_code (`_top_code.py:147-262`): bounds must be finite with magnitude below 2**53; an object (string or Decimal) column parses each value exactly with `Decimal` and fails the whole column with `top_code_non_integral_object_column` on a fractional value (`:268-360`); a numeric column uses `pd.to_numeric`; over the cap gives `over_label`, under the floor gives `under_label`, in range gives a canonical string (`"67"`, never `"67.0"`, `:219-229`); a non-coercible value keeps its text with `format_error`; a `top_code_generalized` warning carries chunk-local counts (`:244-262`).

### Measurement (decides Rust against Arrow)

Probe on the Dell node through `vm-run`, 1,000,000 rows, minimum of five runs (pyarrow 24.0.0, pandas 2.3.3):

| Case | pandas oracle logic | Arrow compute | Ratio |
|---|---|---|---|
| bucketize int64 with 1% nulls, width 10, `range` | 783 ms | 82 ms | 9.5x |
| bucketize string source, width 10, `range` | 1,536 ms | 132 ms | 11.6x |
| bucketize float64, width 2.5, `range` | 2,065 ms | not run (format question below) | |
| top_code int64 with nulls, cap 89 | 1,009 ms | 48 ms | 21x |
| top_code int64 no nulls | 328 ms | | |
| Parquet write and read, int64 column | 23 ms | | |
| Parquet write and read, bucket label strings | 149 ms | | |

Arrow output equals the oracle for int bucketize (`range`, negative values included: `-20--11`) and int top_code. Arrow compute is 48 to 132 ns per row; writing and reading the label column alone is about 149 ns per row. A Rust kernel could save at most the 50 to 80 ns per row of compute, below the I/O floor and inside run-to-run noise end to end. Decision: **a vectorized Arrow operator (`ARROW_PYTHON`, `required_kernel=None`), no Rust.** This matches how redact, truncate and text_redact already run (`execution/_operator_registry.py:141-170`).

The probe also found four facts the design must handle:

1. Arrow formats floats differently: Python and pandas give `20.0`, `-0.0`, `1e-07`; `pc.cast(float64 -> string)` gives `20`, `-0`, `1e-7`.
2. `pc.cast(int64 -> float64)` raises `ArrowInvalid` above 2**53, and the oracle silently loses precision there: both `2**53 + 1` and `9_007_199_254_740_993` bucket to `9007199254740990`.
3. `pd.to_numeric` accepts `" 23"`, `"23.0"` and `"1e2"`, and rejects `"abc"`, `""`, `"0x10"`, `"1_000"`. Arrow's string-to-float cast fails the whole array on the first bad value.
4. The oracle crashes on infinity: a source value `inf` (or the string `"inf"`) raises `OverflowError` out of bucketize's `Int64` cast instead of a coded error.

## 2. Established solutions

Search run: how columnar engines implement fixed-width binning and top-coding (Arrow compute `floor`, `divide`, `if_else`; DuckDB and Polars `cut`/`floor` expressions; sdcMicro `globalRecode` and `topBotCoding`; ARX generalization hierarchies; HIPAA Safe Harbor age rule 164.514(b)(2)(i)(C)), and how other tools keep tolerant numeric parsing vectorized.

- Fixed-width recoding is `floor(x / w) * w` everywhere (sdcMicro `globalRecode` with equal breaks, Polars `floor`); top-coding is a threshold compare with a replacement label (sdcMicro `topBotCoding`). Nothing to invent.
- Tolerant parsing in columnar engines (DuckDB `TRY_CAST`, Polars `strict=False`) is a validity mask plus a cast of the valid values. pyarrow has no `try_cast`, so the standard workaround is a regex mask (`pc.match_substring_regex`) and a cast of the masked values.
- The engine's own precedent is `bucket_perturb` (`execution/native/_bucket_perturb_ext.py:1-40`): keep pandas as the parse authority for the shapes Arrow would read differently, vectorize the rest. This plan uses that split: a fast path for plain numerals and a residue path that calls the same `pd.to_numeric` (bucketize) or `_parse_exact` (top_code) on the few values outside it.

### Reuse inventory

- `kernel/` package, "Arrow kernels" row in CODEMAP ("by kernel operation"): the new array functions go here beside `redact_array` and `truncate_array` (`kernel/_scalar.py`).
- `execution/native/_kernels_scalar.py` (384 lines): the existing home of `native_redact`, `native_truncate`; the two operator entries join it.
- `OperatorSpec.routed_diagnostics` with `reduce_row_error:format_error`, as bucket_perturb and date_shift do (`execution/_operator_registry.py:237`, `:258`), and `reduce_warning:<code>` as fpe does.
- The chunked format-error channel (`execution/native/_chunked_entry.py:315-357`, `_chunked_row_errors.format_error_records`).
- The handlers' own config resolvers (`BucketizeStrategyHandler._resolve_width`, `TopCodeStrategyHandler._resolve_top_bound`, `_resolve_bottom_bound`, `_parse_exact`): called, not copied, so a preset or bound rule has one owner.
- `execution/native/_operator_config_rejections.py`: the home for the config-level declines.

## 3. Guarantee and non-goals

After S2:

1. A `bucketize` or `top_code` column whose source is `int8`-`int64`, `uint8`-`uint32`, `float32`, `float64`, `string` or `large_string`, with no `when:`, runs the Arrow operator on unified slice, chunked, sequential (non-key) and out-of-core, at any row count.
2. Output equals the oracle row for row on every admitted route, except the named changes in section 10, which are made in the oracle too, so oracle and operator agree.
3. Chunk-stable: the output type and every value depend only on the row's value and the config. A column's output type is `string` on every route and every chunk (`int64` for bucketize `lower` with `declared_integer_output` and an int width), whatever the chunk's null content.
4. Thresholds are config literals or presets only. A sentry fails if either handler or operator reads a column statistic.
5. Row errors (`format_error`) and the whole-column failure `top_code_non_integral_object_column` match the oracle by row and code.

Non-goals: Rust; quantile or data-derived bins (none exist); new formats or presets; making `top_code_generalized` counts global on the chunked route (known limitation, `docs/backlog/chunked-audit-evidence-row-indices.md`; counts stay per chunk as today); `decimal128` and bool sources (decline, section 4); FK key columns (decline).

## 4. Enumerations

### Exit paths (per value)

1. null: null, no error.
2. fast-path numeral (integer `^[+-]?\d{1,18}$`, or decimal or exponent form `^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$`, after no trimming): bucketed or top-coded.
3. residue string (whitespace, more than 18 digits, anything else): `pd.to_numeric` on the residue (bucketize) or `_parse_exact` (top_code); a parse gives step 2's result, a failure gives the original text plus `format_error`.
4. non-finite value (`inf`, `-inf`, `nan` from a float source or a string): `format_error`, original value kept (bucketize: was an `OverflowError` crash for infinity; NaN from a float source is null in pandas and stays null).
5. top_code string or object source with a fractional value: whole column fails `top_code_non_integral_object_column` (unchanged, `execution/_strategies/_top_code.py:268-360`); on the chunked and out-of-core routes the transactional sink discards every written chunk.
6. config invalid (bad width, unusable bound, missing `under_label` with `floor`): the handler's existing `StrategyError` at preflight (`execution/_strategies/_top_code.py:362`, `:422-460`; `execution/_strategies/_bucketize.py:146`), before any chunk, on every route.

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

- bucketize: `width`, `preset`, `format`, `declared_integer_output` (`execution/_strategies/_bucketize.py:95-123`).
- top_code: `cap`, `over_label`, `floor`, `under_label`, `preset`.
- All resolved by the handler's own resolvers; the operator takes the resolved values, never the raw config.

### Output surfaces

- Masked column values and type (section 3 item 3).
- Row errors: `format_error` per row.
- Warning `top_code_generalized` with `over_count`, `under_count` (per chunk on the chunked route, as today).
- Route evidence: `arrow_python` backend for the column; the decline `no_native_kernel_or_pool` stops firing for these strategies.

### Codes

No new reason code. Source types outside the domain decline with the existing source-type code family (`string_source_type_rejection`, `execution/native/_real_type_admission.py:93-101`, generalized to read `unified_resident_types`). `reasons.route.NO_NATIVE_KERNEL_OR_POOL` (`reasons/route/_part1.py:136`) stays registered for other strategies.

## 5. Design

1. **Kernel module** `kernel/_bucket.py` (new, about 260 lines): `parse_numeric(arr) -> (ints, floats, residue_mask)`, `bucketize_array(arr, width, fmt, declared_integer) -> (out, error_positions)`, `top_code_array(arr, cap, over_label, floor, under_label, exact_object) -> (out, error_positions, over_count, under_count)`.
   - Integer sources and fast-path integer strings use integer arithmetic: `lower = x - ((x % w) + w) % w` in `int64` via `pc.subtract`, `pc.add` and floored modulo built from `pc.divide` on integers (Arrow integer division truncates toward zero, so the remainder is corrected for negatives). No float cast, so values above 2**53 stay exact.
   - Float sources and decimal strings use `pc.floor(pc.divide(x, w)) * w` in float64, as the oracle does.
   - String output: integer labels via `pc.cast(int64 -> string)` (proven equal to pandas). Float labels via `python_float_str(arr)`: Arrow's cast gives the same shortest round-trip digits as Python's `repr`, so the formatter adds `.0` to a plain integral result, pads a one-digit exponent (`e-7` to `e-07`), and sends any value outside the band where both forms are proven equal to Python `str()` one by one. P3 is the property test that proves the band.
   - The residue path calls the oracle's own parse on the residue values only: `pd.to_numeric(..., errors="coerce")` for bucketize, `TopCodeStrategyHandler._parse_exact` for top_code. Clean data has no residue.
2. **Operator entries** in `execution/native/_kernels_scalar.py`: `native_bucketize`, `native_top_code`, each about 30 lines (resolve config through the handler resolvers, call the kernel, return values plus error positions and warning).
3. **Registry**: two `OperatorSpec`s, `planned_backend=ARROW_PYTHON`, `required_kernel=None`, `positive_kernel_evidence=False`, `unified_resident_types` = the section 3 type set, `full_frame_assembly="type_preserving"`, `routed_diagnostics={"reduce_row_error:format_error"}` (top_code adds `reduce_warning:top_code_generalized`).
4. **Capabilities**: `_capabilities.py:273-300` notes updated; top_code no longer "excluded for lack of a native kernel".
5. **Chunked gate removal**: the bucketize null-count gate (`execution/_planner.py:442-490`, `execution/_chunked_input.py:163-205`) exists only because the pandas output type depended on chunk content. With the type pinned it goes. The `_chunked.py:21-33` docstring is rewritten.
6. **Oracle fixes** (section 10 B2, B3): the handlers call the kernel's integer floor for integer dtypes and map non-finite values to `format_error`. The handler keeps its pandas frame plumbing; the arithmetic for these two cases has one implementation.
7. **Statistic sentry** `tests/sentry/defects/test_bucket_topcode_config_only.py`: AST check that `_bucketize.py`, `_top_code.py`, `kernel/_bucket.py` call no reduction (`min`, `max`, `quantile`, `mean`, `pc.min_max`, `pc.quantile`, `.describe`) on column data. Allowed: none.

Design notes: one parse rule per strategy (fast path plus the oracle's own parse for the residue), one arithmetic implementation for the two fixed cases, one registry fact per operator. Per-column routing (`plan/per-column-routing`) lets a bucketize column run the Arrow operator while a sibling column stays on Python.

## 6. Slices and size

| Slice | Content | Files | Lines (estimate) | Depends on |
|---|---|---|---|---|
| S1 | `kernel/_bucket.py`, two operator entries, two specs, unified slice and chunked admission, oracle fixes B2 and B3, removal of the bucketize null-count gate, statistic sentry, contract text, changelog | `kernel/_bucket.py`, `kernel/__init__.py`, `execution/native/_kernels_scalar.py`, `execution/_operator_registry.py`, `execution/native/_capabilities.py`, `execution/native/_real_type_admission.py`, `execution/native/_operator_config_rejections.py`, `execution/_strategies/_bucketize.py`, `execution/_strategies/_top_code.py`, `execution/_planner.py`, `execution/_chunked_input.py`, `execution/_chunked.py`, `execution/physical/_shadow_full_frame.py:115-120`, docs, tests | source about 420, tests about 450 | none |
| S2 | Sequential and out-of-core: add the two strategies to the sequential `NativeOp` descriptors and the out-of-core column gate, following bucket_perturb | `execution/_sequential_native_ops.py`, `execution/out_of_core/_hash_run.py` (or a sibling if it passes 600 lines), tests | source about 90, tests about 200 | S1 |

`execution/_sequential_native_ops.py` and `execution/out_of_core/_hash_run.py` sizes are checked at S2 start; a file that would pass 600 lines gets a sibling module, not a raised ceiling.

Existing tests whose assertions flip (listed in the builder report): planner tests that expect the bucketize null-count gate (`grep -rn "bucketize" tests/unit/execution/test_planner*.py tests/native`), any test that expects `no_native_kernel_or_pool` for these strategies, and oracle tests that pin the old precision loss or the infinity crash (none found by `grep -rn "OverflowError" tests | grep -i bucket`; the builder confirms). Changed assertions and moved gating are full-suite triggers, so S1 runs T3 on the merge head.

## 7. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `_bucket.py` | `src/decoy_engine/kernel/` | "Arrow kernels: `src/decoy_engine/kernel/`, by kernel operation" | `_scalar.py`, `_code_set.py` |
| `test_bucket_kernel.py` | `tests/unit/kernel/` | unit tests mirror `src/` | existing kernel tests |
| `test_bucket_topcode_native.py` | `tests/parity/` | cross-route parity | `test_chunked_substrate_parity.py` |
| `test_bucket_topcode_config_only.py` | `tests/sentry/defects/` | "Sentry test" | other defect sentries |

CODEMAP's `kernel/` row (line 120) gains `bucketize_array`, `top_code_array`. The sentry gets a row in `scripts/dev/sentry_registry.toml`.

## 8. Class table (catalog `recurring-defects.md`)

| # | Class | Applies | Structure and proof | Mutation that must turn it red |
|---|---|---|---|---|
| 1 | Anchored validation | yes: the fast-path numeral regexes | `pc.match_substring_regex` with `^...$` over the whole value; Arrow's RE2 `$` does not match before a trailing newline, and P2 has a `"23\n"` cell that must go to the residue path | drop the `^` anchor (P2 `"x23"` cell red) |
| 2 | Strict wire and stored types | no persisted model | n/a | n/a |
| 3 | No exception context | the whole-column `top_code_non_integral_object_column` raise | keeps the handler's existing value-free message, raised by the handler code path | existing value-free sentries |
| 4 | Versioned read models | no reader | n/a | n/a |
| 5 | Normalized guard scanners | statistic sentry | AST walk over call nodes, attribute and name forms (`pc.quantile`, `col.max()`, `np.percentile`, `getattr(pc, "min_max")`) | add `col.max()` to `_top_code.py` (red); add `getattr(pc, "quantile")` (red) |
| 6 | No reaching into private modules | operator calls handler resolvers | the resolvers are in the same package (`execution`); the kernel module imports nothing from `execution` (import-linter: `kernel` is below `execution`) | import a handler from `kernel/_bucket.py` (import-linter red) |
| 7 | No hidden CI failures | none new | n/a | n/a |
| 8 | One input, one trust class per entry point | no new entry point | n/a | n/a |
| 9 | Mutations on the final head | named mutations below rerun after the last change | gate record | n/a |
| 10 | Allowlisted helpers still checked | the statistic sentry has an empty allowlist | sentry asserts it is empty | add an allowlist entry (red) |
| 11 | No raised caps | module-size ceilings | no ceiling raised; S2 splits a file instead | n/a |

### Harness defect classes (`docs/handoffs/DEFECT-CATALOG.md`)

| # | Class | Where it applies | Closing structure | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | `format_error` reasons and the whole-column error | fixed reason text, never the value | existing value-free sentries, P5 asserts text | put the value in the reason (sentry red) |
| 2 | Cleanup missing on an exit path | whole-column failure after earlier chunks are written | the transactional sink discards on failure (existing); P6 checks no output file remains | P6 | commit chunks before the column check (P6 red) |
| 3 | State and concurrency | per-chunk invocation | the kernel is a pure function of array and resolved config; no module state | P4 chunk-size sweep | cache a parsed width at module level keyed by column name (P4 two-config cell red) |
| 4 | Route parity and silent fallback | five routes | one kernel; parity per route; residue path is the oracle's parse | P4, P7 | skip the residue path and mark residue as `format_error` (P2 `" 23"` cell red) |
| 5 | Referential integrity | FK key columns | decline on key columns | P8 | admit on a key (P8 red) |
| 6 | Untrusted producer | source values | hostile corpus P2 through kernel and oracle | P2 | treat `"1_000"` as 1000 (P2 red) |
| 7 | Check then use | N/A: the parse mask and the cast run over the same immutable Arrow array in one call | n/a | n/a | n/a |
| 8 | Weak tests | equality without types | P4 compares Arrow tables with schema and output hash | P4 | compare `to_pylist()` only (reviewer check) |
| 9 | Refactor drift | removing the bucketize null-count gate | flipped planner tests listed; P4 proves the gate is no longer needed | P4 null-heavy chunk cells | restore the pandas route for one chunk (P4 type cell red) |
| 10 | Frozen contract drift | contract text on chunked bucketize and top_code; B1-B4 | contract rewritten, Breaking fragment | docs review, P3, P5 | keep old "null-free numeric" wording (reviewer check) |

## 9. Acceptance tests (each fails before its slice unless marked)

- **P1 kernel units (S1).** `bucketize_array` and `top_code_array` against hand-written expectations for every format, every preset, negative values, width 1, widths 3 and 2.5, `declared_integer_output`, hipaa_age, floor with under_label. Fail-before: module absent.
- **P2 hostile corpus (S1).** Kernel and oracle on the same values: `" 23"`, `"23 "`, `"23\n"`, `"+23"`, `"-0"`, `"23.0"`, `"1e2"`, `"1E+2"`, `".5"`, `"5."`, `"abc"`, `""`, `"0x10"`, `"1_000"`, `"٣"` (Arabic-Indic digit), a 25-digit integer string, `"inf"`, `"nan"`, `"89.5"` (top_code: whole-column failure), `"89.000"` (integral). Output and `(row, code)` row errors equal, except the named B3 cells. Fail-before: no kernel.
- **P3 float format property (S1).** `python_float_str` equals `[str(v) for v in values]` on 1,000,000 random doubles drawn across every binary exponent, plus `0.0`, `-0.0`, subnormals, `2**53 ± 1`, `1e15`, `1e16`, `1e-4`, `1e-5`, `0.1 + 0.2`. Fail-before: function absent.
- **P4 route parity (S1).** Each strategy, sources int64 (with and without nulls), float64, string; 2,000 rows (unified slice) and 120,000 rows at chunk sizes 1,000, 7,919 and 50,000, including a chunk that is all null: the column's route is `arrow_python`, the output equals forced full frame as an Arrow table (schema included) and by hash, the output type is `string` in every chunk. Fail-before: full frame, or chunked pandas with a chunk-dependent type.
- **P5 row errors (S1).** A string column with 1% non-numeric values: row errors equal the oracle's on full frame, unified slice and chunked (global row indices on chunked). Fail-before: no native row errors.
- **P6 whole-column failure (S1).** top_code on a string column whose 90,000th value is `"89.5"`, 120,000 rows chunked: the run fails with `top_code_non_integral_object_column` and the sink leaves no output. Unchanged-behavior control on full frame.
- **P7 sequential and out-of-core (S2).** Two-table FK job, both strategies on non-key child columns: native route recorded, output equals forced full frame. Fail-before: Python handler.
- **P8 FK key (S2).** Either strategy on a key column declines to the handler. Unchanged-behavior control.
- **P9 HIPAA template (S1).** The CLI `hipaa` template's top_code column (age, `hipaa_age`) at 120,000 rows runs `arrow_python`. Fail-before: pandas.
- **Sentry (S1).** `test_bucket_topcode_config_only.py` passes and fails on its seeded cases.

Named mutations (record the head): integer floor without the negative correction (P1 `-15` cell red); float cast for int sources (P2 25-digit cell and B2 cell red); drop the `.0` suffix rule in `python_float_str` (P3 red); skip the residue path (P2 red); emit `top_code_generalized` counts as zero (P4 warning cell red); restore the null-count gate (P4 route assertion red).

Performance evidence (performance.md): the section 1 probe rerun through the real operator at 120,000 and 1,000,000 rows, three runs each on the Dell node, wall time and peak RSS, before and after, in the PR body.

## 10. Frozen contracts and byte changes

Named changes (fragment and contract):

1. **B1 type pin.** An empty or all-null bucketize or top_code column is typed `string` on every route (was the source type, for example `double` or `null`, on pandas). `declared_integer_output` columns are typed `int64`.
2. **B2 exact large integers (oracle and operator).** Integer sources with magnitude above 2**53 bucket exactly, because the arithmetic stays in `int64`. Example, width 10: `4611686018427387911` (2**62 + 7) was labelled `4611686018427387904` through float rounding; it is now `4611686018427387910`. Values with magnitude at or below 2**53 are unchanged.
3. **B3 infinity (oracle and operator).** A source value of `inf` or `-inf` (float or the string forms `pd.to_numeric` accepts) under bucketize gives a `format_error` row error and keeps its value; before, the run crashed with an uncoded `OverflowError`. top_code over a float infinity is unchanged (`inf > cap` is over the cap, as before).
4. **B4 chunked gate.** bucketize columns with nulls or a string source now run chunked; before they ran whole-frame. Values are unchanged.

Fragment first line: `Breaking: bucketize and top_code now run a vectorized Arrow operator on every route; an empty or all-null output column is typed string, integers above 2**53 bucket exactly, and an infinite source value under bucketize is a format_error row instead of a crash.`

Contract: `docs/compatibility-contract.md` chunked-strategy paragraph (bucketize "null-free numeric" condition) and the route table entries for both strategies. `SEED_PROTOCOL_VERSION`, plan serialization and digests do not change (neither strategy is keyed).

## 11. Pre-mortem

- Arrow and Python disagree on some float digits. P3 covers every exponent band; a value outside the proven band goes through `str()`, so the worst case is speed, not bytes.
- Arrow integer division and modulo semantics differ by version. The kernel uses only `pc.divide` on integers plus an explicit floored-remainder correction, and P1 runs negative cells; the CI pyarrow floor (`pyproject.toml`) is the version P1 runs on.
- Residue-heavy columns (most values with spaces) run near oracle speed. Correct, just not faster; P2 proves correctness and the run card shows `arrow_python`.
- Removing the bucketize null-count gate exposes a dtype hazard somewhere else in the chunked substrate. P4's all-null chunk and null-heavy cells cover it.

## 12. Owner questions

None blocking. The Rust option is closed by the measurement; reopen only if a profile shows these operators above 20% of a real run.

## 13. Deferred (V2-LOG)

- **V2-LOG:** `top_code_generalized` counts summed across chunks (with the shared chunked-evidence fix).
- **V2-LOG:** `decimal128` and bool sources.
