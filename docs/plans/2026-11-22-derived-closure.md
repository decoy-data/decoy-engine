Status: plan (revision 1, 2026-11-22)

# DERIVED-CLOSURE and FORMULA-PARSE-ONCE: compile each expression once per column

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap rows: DERIVED-CLOSURE and FORMULA-PARSE-ONCE (V1 engine, approved 2026-11-22), from the fast-path exceptions study (vault `10_Projects/decoy/fastpath-exceptions-study-2026-11-22.md`, section 1) and the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`). DERIVED-CLOSURE folds in one more change: `derived_aggregate` refuses `sum` and `mean` over non-numeric values with a coded error.

**Why one plan for two rows.** Both rows remove the same cost: an expression that is parsed or walked again for every row. Both live in `src/decoy_engine/expressions/`, both promise byte-identical output, and both are proved the same way (a differential test against a frozen copy of today's evaluator). They stay separate slices because they touch different evaluators (Lark for `derived`, simpleeval for `formula`) and can merge in either order.

Anchors: paths are in this repository (decoy-engine), read at `origin/main` `70881ad79`. Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN, choke point, placement), `profiles/local-operations.md`, `feature-dev.md`, `performance.md`, `refactoring.md`, `cross-cutting-concerns.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md`, `architecture.md`, `security.md`, `api-and-compatibility.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where Things Go"); GEN-STREAM-ALL plan (`origin/plan/gen-stream-all` `008acffed`, which keeps `derived` and `formula` as named generation exceptions).

Risk: R2. The `derived` and `formula` evaluators are sandboxes (closed grammar and simpleeval), and the `derived_aggregate` refusal changes output for one input shape. Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

## 1. Frame

Evidence (study, Dell node, 200,000 rows):

| Case | Today | Faster build, same output |
|---|---|---|
| `derived` `price * qty` | 10.75 s | plain Python 0.021 s |
| `derived` `concat(first, " ", last)` | 35.4 s | plain Python 0.108 s |
| `derived` `case_when(price > 400, "high", price > 100, "mid", "low")` | 51.2 s | plain Python 0.026 s |
| `formula` `value.upper()` | 7.61 s | simpleeval parse-once 0.88 s |
| `formula` `value[:2] + '***'` | 6.85 s | simpleeval parse-once 1.43 s |

Where the time goes:

- `derived`, per row: `column_refs(config.compiled)` walks the whole parse tree (`transforms/derived.py:271`, `expressions/_lark_parser.py:201-208`); `_coerce_context` copies the context; `evaluate` builds a new `_ExprTransformer` and runs `_LazyEvaluator`, a task-stack walk with tuple allocation and `getattr` dispatch per node (`expressions/_lark_parser.py:250-362`). The mask handler also builds a dict per row (`execution/_strategies/_derived.py:92-115`). The generate side builds a dict of every generated column per row, not only the referenced ones (`generation/_synthesize_derived.py:56-58`).
- `formula`, per row: `safe_eval` copies the scope, filters callables and builds a new `EvalWithCompoundTypes`, which parses the text again (`expressions/_safe_eval.py:129-154`). Mask side: `transforms/formula.py:59`. Generate side: `generators/_formula.py:303` (inline) and `:232` (referenced post-pass); the inline path also rebuilds the full 25-entry scope per row (`:298`, `_formula_scope` at `:311-386`), though only `hash` depends on the row.
- `derived_aggregate` `sum` over an object column of strings concatenates (pandas `Series.sum`, `transforms/derived_aggregate.py:174`; the study measured `"bac"`). Every CSV source column is read as `string` (`io/bounded_reader.py:298-302`), so `op: sum` on an undeclared CSV column writes a concatenation of every value into every row. `mean` over strings raises an uncoded `TypeError`.

## 2. Established solutions

- **Closure compilation of an AST.** Compile the tree once into nested Python closures, then call the root per row. Standard interpreter technique ("closure compilation", Feeley and Lapalme 1987, "Using closures for code generation"); used by template engines and rule engines that cannot use `exec`. No source text is generated and nothing is passed to `compile` or `exec`, so the closed-grammar property holds.
- **Parse once, evaluate many.** simpleeval documents `eval(expr, previously_parsed=...)` and `parse(expr)` for this case (simpleeval README, "Compound types ... previously_parsed"). The installed version has it (`SimpleEval.eval(self, expr, previously_parsed=None)`).
- **Differential testing against a frozen oracle.** Hypothesis generates expressions from the grammar and compares the new evaluator with a verbatim copy of today's. Same pattern as the engine's parity suites (`tests/parity/`).
- **SQL aggregate typing.** SQL `SUM` and `AVG` are defined on numeric types only; a string argument is a type error (ISO/IEC 9075-2, set functions). The refusal follows that rule.

### Reuse inventory

- `expressions/_lark_parser.py`: `compile_expr` (`:79`), `CompiledExpression` (`:65`), `column_refs` (`:201`), `evaluate` (`:250`), `_parse_date`, the operator bodies in `_ExprTransformer` (`:365-545`). The operator bodies move into the closure builders unchanged.
- `transforms/derived.py`: `DerivedConfig`, `_coerce_context`, `_apply_bounds`, `apply_derived` (`:238`), `failure_reason`, `failure_text`. The one per-row failure text stays.
- `execution/_strategies/_derived.py:84-116` mask handler and `generation/_synthesize_derived.py:30-59` generate path: the two callers.
- `expressions/_safe_eval.py` `safe_eval`, `make_mask_globals`, `BASE_GLOBALS`, `formula_is_evaluable`: the one sandbox.
- `transforms/formula.py` `FormulaStrategy.apply`; `generators/_formula.py` `_eval_formula_inline`, `_formula_scope`, the referenced post-pass at `:200-240`.
- `transforms/derived_aggregate.py:157-184` `apply_derived_aggregate`: the one place both the mask handler (`execution/_strategies/_derived_aggregate.py`) and the generate path call.
- `reasons/runtime/_part1.py:188-191`: the registration form for runtime codes (`_d(code, text, since=...)`).

## 3. Guarantee and non-goals

After this plan:

1. `derived` output (values, Python types, Arrow type, nulls, failure text, failure row) is byte identical to `70881ad79` for every expression the grammar accepts and every row, on mask and generate.
2. A compiled `derived` expression is walked once per column, not once per row; its column references are computed once.
3. The generate side reads only the referenced columns per row.
4. `formula` output (values, RNG draws, failure text, failure row) is byte identical to `70881ad79` on mask and generate. The text is parsed once per column.
5. `derived_aggregate` with `op: sum` or `op: mean` over a column with any non-null non-numeric value refuses with the registered code `derived_aggregate_non_numeric` and a value-free message. `min`, `max` and `count` are unchanged.
6. At 200,000 rows: `derived` at least 50 times faster on the three study cases; `formula` at least 4 times faster on the two study cases (mask side).

Non-goals: an Arrow compile of `derived` (DERIVED-ARROW, 1.0.x); `derived` leaving the oracle route or joining the chunked lane; streaming `derived` or `formula` in generation; any change to the grammar, the simpleeval allowlist or the formula scope; chunking `derived_aggregate` (WHOLE-COLUMN-PREPASS, 1.0.x); parsing numbers out of string columns for `derived_aggregate`.

## 4. Enumerations

### Exit paths

- Compile errors, unchanged and still at config parse: `ValidationError` for length, paren depth, grammar, string escapes and dunder names (`expressions/_lark_parser.py:79-198`); `derived_expression_missing`, `derived_bounds_invalid`, `derived_bounds_inverted`, `derived_null_propagation_invalid`.
- Row evaluation errors, unchanged: `derived_evaluation_failed` (mask handler) and `ValueError` (generate) with `failure_text`, at the same first failing row. A dunder column reference still raises only when that branch is evaluated, as today.
- `derived_ref_missing` (mask handler, before any row): unchanged.
- `formula`: a `SyntaxError` or simpleeval `InvalidExpression` still surfaces at the first evaluated row, not at column start, so an all-null or empty column still does not raise (section 5). Generate failures keep `_raise_evaluation_failed` and `_failure_reason`.
- New: `derived_aggregate_non_numeric` (runtime namespace), raised by `apply_derived_aggregate` before any row is written, on mask and generate.

### Routes and codes

- Mask: `derived`, `formula` and `derived_aggregate` run on the full-frame oracle route, as today; every chunked and out-of-core decline (`out_of_core_dynamic_output_type_unsupported`, `strategy_not_chunk_safe`) is unchanged.
- Generate: `derived`, `formula` and `derived_aggregate` stay on the legacy generation path (GEN-STREAM-ALL keeps `gen_legacy_derived` and the formula decline; this plan does not touch admission).
- Route labels: no change; no route code added. The one new code is a runtime refusal, registered in `reasons.runtime`, not `reasons.route`.

### FK shapes

N/A: none of the three strategies is admitted as an FK key or FK child (`join_safe = False` on each handler); no FK path is touched.

### Fields

- `CompiledExpression` gains `refs: tuple[str, ...]` (sorted column references) and a private compiled callable. `source` and `tree` stay, so `column_refs` on a subtree still works.
- `DerivedConfig`: unchanged fields.
- Config schema: unchanged (no new key in `pipeline-config.schema.json`).

### Output surfaces

- `derived` and `formula` column values: identical.
- `derived_aggregate` values: identical for numeric input; a refusal instead of a concatenated string for `sum` over strings; a coded refusal instead of an uncoded `TypeError` for `mean` over strings.
- Reason registry: one new runtime code; the f29 reason fixtures (`tests/fixtures/f29/reason-baseline.json`, `reason-manifest-v1.json`, `reason-registry-release.json`) gain its row through their own regeneration scripts.
- Draw-site inventory text (`execution/native/_draw_sites_mask.py:389`, `_draw_sites_gen.py:164`): the `call_shape` strings name `safe_eval` per row; S3 updates them to the parse-once shape. The draw order does not change.

## 5. Design notes

No new module unless the size cap forces one (below). Principles: one place per fact (operator semantics live in one set of builders, not in a transformer plus an evaluator); single-purpose functions; no flag arguments.

### S1: `derived` closure compiler

In `expressions/_lark_parser.py`:

- `compile_expr` builds, after its existing checks, `refs` and a root closure `fn(ctx: Mapping[str, Any]) -> Any`. `evaluate(compiled, ctx)` becomes `compiled.fn(ctx)`; its signature and errors stay. `column_refs` returns `frozenset(compiled.refs)` for a `CompiledExpression` and still walks a subtree.
- One builder per grammar rule in a table `_BUILDERS: dict[str, Callable[[Tree, Compile], Closure]]`. Each builder holds the operator body moved verbatim from `_ExprTransformer`. `_ExprTransformer` and `_LazyEvaluator` are deleted, so there is one evaluator.
- Pass-through rules (`start`, `expr`, `paren_expr`, single-child `ternary`, `or_expr`, `and_expr`, `not_expr`, `compare_expr`, `add_expr`, `mul_expr`, `unary_expr`) compile to their child's closure, with no extra frame.
- Literals (`number_lit`, `string_lit`, `true_lit`, `false_lit`, `none_lit`) are decoded once at compile time and become constant closures. The decode is the same code, so the value is the same.
- Semantics that must be kept exactly, each pinned by the differential test:
  - Operand order is left to right, and every operand of `compare_expr`, `add_expr`, `mul_expr`, `concat_op`, `slice_op`, `days_between_op` and `list_literal` is evaluated before the operator runs, as `_LazyEvaluator` does (`"apply"` after all children). A comparison chain computes every comparison, folding with `result = result and cmp`, and does not stop at the first `False` (today's `compare_expr`, `:398-422`).
  - Only `ternary`, `case_when_op`, `or_expr` and `and_expr` are lazy. `or` and `and` return an operand, not a bool, and stop at the first deciding operand (`_logic_step`, `:345-362`). `case_when` tries pairs in order and falls through to the default (`_case_when_step`, `:327-343`).
  - `col_ref` reads `ctx[name]` when called, and a dunder name raises `ValidationError` when called (not at compile), so an unchosen branch never raises, as today.
- **Call depth.** `_LazyEvaluator` is iterative so that no admitted tree can raise `RecursionError`. Closures call each other, so depth must be bounded by construction. The only shapes that nest without parentheses are right-nested `ternary`, chained `not_op` and chained `neg_op`. The compiler flattens each into one closure that loops: a ternary chain becomes a list of `(cond, then)` pairs plus a final else; `not not not x` applies `not` in a loop the same number of times; `- - x` applies unary minus in a loop. Every other nesting needs a parenthesis, and `compile_expr` caps paren depth at 50 (`:61`, `:124-139`). So the closure depth is at most a small constant times 51. The compiler computes that depth for each expression and a test asserts it stays under 300 for the worst admitted shapes (A4).

In `transforms/derived.py`:

- `apply_derived` uses `config.compiled.refs` instead of `column_refs(...)` per row. Its signature, null handling, bounds and failure text stay.
- New `apply_derived_column(config, columns, n, *, column)`: the one per-row loop. `columns` maps each ref to a sequence (or `None` when absent). For row `i` it builds the small dict of refs only; a ref that is absent or shorter than `i + 1` is left out, so `apply_derived` raises the same "a referenced column is missing" text as today. It raises on the first failing row with the same text.
- The mask handler calls it with the `df[refs]` columns (it keeps the zero-ref case and `derived_ref_missing`). The generate path calls it with `{ref: generated.get(ref) for ref in refs}`, so it no longer copies every generated column per row.

**Size and placement.** `_lark_parser.py` is 555 lines; deleting `_ExprTransformer` and `_LazyEvaluator` (about 300 lines) and adding the builders (about 250) keeps it near 500, under the 600 aim. If it passes 600, the builders move to `expressions/_lark_closures.py` and CODEMAP gains a row for `src/decoy_engine/expressions/` (no row today), in the same slice. No public name is added; `evaluate`, `compile_expr`, `column_refs` and `CompiledExpression` keep their names and signatures.

### S2: `derived_aggregate` numeric refusal

- `apply_derived_aggregate` (`transforms/derived_aggregate.py:157`) checks, for `sum` and `mean` only: the series is numeric (`pandas.api.types.is_numeric_dtype`, which includes bool), or it is object dtype and every non-null value is a `numbers.Number` and not a `str` or `bytes`. Otherwise it raises `ExecutionError(code=reasons.runtime.DERIVED_AGGREGATE_NON_NUMERIC)` before computing anything. An empty or all-null column passes, as today (`sum` gives 0, `mean` gives NaN, written as null).
- Message, value-free: `derived_aggregate op 'sum' needs a numeric source column; column {name!r} holds non-numeric values. Declare the column with a numeric type (see docs/declared-casting.md) or use op 'count', 'min' or 'max'.` The column name is config text, not data; no cell value appears.
- The error is raised after any `try` block closes (recurring class 3).
- One check, at the one function both callers use: the mask handler and `generate_derived_aggregate_column` both go through `apply_derived_aggregate`, so the rule is enforced by construction.

### S3: `formula` parse once

In `expressions/_safe_eval.py`:

- New `FormulaProgram(expr: str, globals_: Mapping[str, Any])`. It keeps the base scope (minus `__builtins__`), the base `functions` (callables in the base scope) and one `EvalWithCompoundTypes`. Method `eval(locals_)`: sets the evaluator's `names` to the base scope updated with `locals_`, and its `functions` to the base functions plus the callables in `locals_` (exactly what `safe_eval` computes today), then calls `eval(expr, previously_parsed=tree)`.
- The tree is parsed on the first `eval` call and cached. A parse failure is not cached: each call raises the same `SyntaxError` again, so failures happen at the first evaluated row, as today, and an empty or all-null column never raises.
- `safe_eval(expr, globals_, locals_)` becomes `FormulaProgram(expr, globals_).eval(locals_)`, so one code path remains.
- Mask (`transforms/formula.py:59`): one `FormulaProgram(expr, scope)` per column; `column.apply(lambda v: v if pd.isna(v) else program.eval({"value": v}))`. The `random.Random` and its draw order are unchanged.
- Generate inline (`generators/_formula.py:290-308`): one program per column. The scope is built once per column, since every RNG closure captures the same `row_rng` and the same Faker instance; per row the loop reseeds as today and overwrites only `hash` (it captures `local_seed`), `i` and `index`. Referenced post-pass (`:200-240`): one program per column, with the same per-row scope updates as today.
- A test pins the installed simpleeval floor (`simpleeval>=1.0.5`, `pyproject.toml:110`) by asserting `previously_parsed` is in the `eval` signature.

### Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `test_lark_closure_differential.py` | `tests/unit/expressions/` | "Unit tests": `tests/unit/<package>/` mirroring `src/` | existing expression tests |
| `_legacy_lark_eval.py` (frozen oracle, test only) | `tests/unit/expressions/` | "Unit tests" | the differential test |
| `test_formula_parse_once.py` | `tests/unit/expressions/` | "Unit tests" | the same |

Size: S1 about 300 changed source lines in two files and 400 test lines; S2 about 40 source lines and 80 test lines; S3 about 80 source lines in three files and 150 test lines.

## 6. Defect classes

### Plan-contract catalog (docs/handoffs/DEFECT-CATALOG.md)

| # | Class | Where it could appear | Closing structure | Test | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | failure text, the new refusal message | `failure_text` stays the one row-failure text; the refusal names op and column only | A3, A8 | put the first value in the refusal (A8 red) |
| 2 | Cleanup missing on an exit path | none: no resource is opened | N/A: pure in-memory evaluation, nothing to release | none needed | N/A: no resource |
| 3 | State and concurrency | the cached formula tree and the reused evaluator | one `FormulaProgram` per column per call, never module level; failed parses not cached | A10 | cache the program at module level (A10 red: two columns share state) |
| 4 | Route parity and silent fallback | mask vs generate evaluation | both sides call `apply_derived_column` and `FormulaProgram`; `derived_aggregate` both call `apply_derived_aggregate` | A2, A9, A12 | let generate keep its own loop (A2 red on a short sibling) |
| 5 | Referential integrity | N/A: no key column; these strategies are not join-safe | N/A: no FK path touched | none needed | N/A: nothing to break |
| 6 | Untrusted producer | expression text, cell values | unchanged sandboxes: closed grammar, no `exec`; simpleeval allowlist unchanged | A1, A6 | add `exec`-based codegen (A6 red: sentry finds `compile`/`exec`) |
| 7 | Check then use | refs checked, then read per row | refs come from `compiled.refs`, the same tuple the handler checks for `derived_ref_missing` | A2 | read refs from a re-walked tree (A2 equality kept, mutation M3 red) |
| 8 | Weak tests | differential on trivial expressions | Hypothesis grammar-driven expressions with nulls, NaN, -0.0, non-ASCII, bools, mixed types; error-type equality | A1, A5 | drop eager operand evaluation in compare chains (A1 red) |
| 9 | Behavior-preserving refactor drift | removing `_LazyEvaluator` and `_ExprTransformer` | frozen copy of both as the oracle; existing suites unchanged | A1, A5 | M1, M2 |
| 10 | Frozen contract drift | reason registry, output bytes | one additive code with `since=`; `Breaking:` line for the `sum`-over-strings change | A8, A11 | N/A for S1 and S3 (no contract surface) |

### Recurring defect classes (dev-rules catalog)

| # | Class | Applies | How |
|---|---|---|---|
| 1 | Anchored validation | no | no new string validation |
| 2 | Strict wire types | no | no persisted model |
| 3 | No exception context | yes | S2 raises after the check, outside any `except`; A8 asserts `__cause__` and `__context__` are `None`; `apply_derived_column` keeps the "raise outside the block" rule (`execution/_strategies/_derived.py:108-115`) |
| 4 | Versioned read models | no | none |
| 5 | Normalized guard scanners | yes | A6 scans `expressions/` for `exec`, `eval`, `compile` calls through the AST, covering `builtins.exec` and aliases |
| 6 | No private reaching | yes | handlers import `decoy_engine.expressions` public names and `transforms.derived` functions only |
| 7 | No hidden CI failures | yes | no skips; Hypothesis runs with a fixed `derandomize` profile in CI |
| 8 | One trust class per entry point | no | none |
| 9 | Mutations on final head | yes | rerun per slice on the final head, head recorded |
| 10 | Allowlisted helpers checked | no | no allowlist |
| 11 | No raised caps | yes | `_lark_parser.py` must stay under its module-size ceiling; if not, split, never raise the ceiling |

## 7. Acceptance tests (each with its fail-before)

- **A1** (S1) Differential, Hypothesis, 2,000 examples: expressions generated from the grammar (every rule, nesting to depth 6, columns `a` to `d`), rows with ints, floats (including `nan`, `inf`, `-0.0`), strings (non-ASCII, digits, ISO dates), `True`, `False`, `None`, lists. For each, the new `evaluate` and the frozen oracle give the same `(type, repr)` or raise the same exception type. Fail-before: n/a for an identity change; its power is shown by M1 and M2.
- **A2** (S1) Generate parity: `_derived_generate` with a sibling shorter than `n` and with a sibling declared after the column gives the same output and the same failure text and row as `70881ad79`. Fail-before: n/a (identity); M4 shows power.
- **A3** (S1) The existing derived suites (`tests/unit/transforms/` derived tests, `tests/unit/execution/` derived handler tests) pass unchanged.
- **A4** (S1) Depth: a 4,096-character `not not ... x`, a 4,096-character right-nested ternary chain, and a 50-paren nest with an operator at each level all evaluate, and the computed closure depth is under 300. Fail-before: without the flattening the first two raise `RecursionError` (shown by M5).
- **A5** (S1) Short-circuit pins: `x if c else 1 // 0` with `c` true does not raise; `name or "unknown"` returns `name`'s value; `1 < 2 < "a"` raises `TypeError` (eager chain).
- **A6** (S1) Sandbox sentry: `expressions/` contains no call to `exec`, `eval`, `compile` or `builtins.*` versions of them (AST walk with aliases). Fail-before: a seeded `exec(...)` in a scratch copy is found.
- **A7** (S1) Speed (Dell node through `vm-run`, three runs after a warmup, median and spread in the PR): the three study cases at 200,000 rows are at least 50 times faster through the mask handler.
- **A8** (S2) `derived_aggregate` `sum` over `["b", "a", "c"]` (object) and over a CSV-read string column refuses with `derived_aggregate_non_numeric`; the message holds no cell value; `__cause__` and `__context__` are `None`. `mean` over strings gives the same code. `min`, `max`, `count` over strings are unchanged. `sum` over ints, floats, bools, Decimals and an all-null column are unchanged. Fail-before: `sum` returns `"bac"` and `mean` raises an uncoded `TypeError` at `70881ad79`.
- **A9** (S2) The same refusal on the generate path (`generate_derived_aggregate_column` over a string sibling). Fail-before: returns the concatenation.
- **A10** (S3) Formula differential: a corpus of formulas (`value.upper()`, slicing, `re` proxy, `randint` and `choice`, `hash(value)`, `date_between`, `now()`, a syntax error, an undefined name, a blocked attribute) on mask and generate (inline and referenced) gives the same values, the same RNG sequence and the same failure text and row as a frozen copy of `safe_eval`. Two formula columns in one job keep independent RNG streams. Fail-before: n/a (identity); M6 and M7 show power.
- **A11** (S3) An empty column and an all-null column with a formula that has a syntax error do not raise (as today). Fail-before: n/a; M6 shows power.
- **A12** (S3) Speed: the two study formulas at 200,000 rows on the mask side are at least 4 times faster (Dell, same protocol as A7).

## 8. Named mutations

- M1 S1: make `or` return `bool(result)` -> A1 and A5 red.
- M2 S1: stop a comparison chain at the first `False` -> A1 and A5 red.
- M3 S1: compute refs per row from the tree again -> A7 fails its target (perf guard), and the unit test that asserts `column_refs` is not called per row (a counting spy) is red.
- M4 S1: build the generate row context without the "shorter than `i + 1`" rule -> A2 red.
- M5 S1: drop the ternary-chain flattening -> A4 red (`RecursionError`).
- M6 S3: parse eagerly at `FormulaProgram` construction -> A11 red.
- M7 S3: reuse the base `functions` without adding per-row callables -> A10 red (`hash` and `randint` from the row scope are not callable by name).
- M8 S2: check only `sum`, not `mean` -> A8 red on `mean`.

## 9. Slices

| Slice | Row | Content | Size | Risk |
|---|---|---|---|---|
| S1 | DERIVED-CLOSURE | closure compiler, cached refs, `apply_derived_column`, both callers, A1 to A7 | 1.0 | R2 (sandbox evaluator) |
| S2 | DERIVED-CLOSURE | `derived_aggregate_non_numeric` refusal, A8, A9 | 0.25 | R2 (named output change) |
| S3 | FORMULA-PARSE-ONCE | `FormulaProgram`, three callers, draw-site text, A10 to A12 | 0.5 | R2 (sandbox evaluator) |

S1, S2 and S3 are independent; any order works. Each slice adds a `changelog.d/` fragment. S2's fragment carries the `Breaking:` line: "`derived_aggregate` `sum` and `mean` over a non-numeric column now refuse with `derived_aggregate_non_numeric`; before, `sum` concatenated the strings and `mean` raised an uncoded error." Test depth: T0 per edit and T1 impact-selected per commit. S2 touches the reason registry and its fixtures; the f29 reason sentries are in the T1 selection. No other escalation trigger applies.

## 10. Frozen contracts

- Reason registry (`reasons/_registry.py` and the f29 fixtures): one additive runtime code, `derived_aggregate_non_numeric`, with `since=` the next registry minor. Additive members are allowed by the registry contract; no code is renamed or removed.
- Output bytes: unchanged for `derived` and `formula`. For `derived_aggregate`, the one changed case is named above and on the changelog `Breaking:` line.
- Public names in `decoy_engine.expressions` (`compile_expr`, `evaluate`, `column_refs`, `CompiledExpression`, `safe_eval`): names and signatures unchanged. `CompiledExpression` gains a field; it is constructed only by `compile_expr`.
- Seed protocol: unchanged (no draw moves), so `SEED_PROTOCOL_VERSION` stays.

## 11. Pre-mortem

- **A semantic detail of the old walker is missed** (eager chains, operand-returning `or`, the time a dunder name raises). The frozen oracle plus grammar-driven Hypothesis is the guard; A5 pins the known traps by name.
- **Recursion in a shape the plan did not list.** If the builder finds a nesting without parentheses other than ternary, `not` and unary minus, stop and report; do not raise the recursion limit.
- **`_lark_parser.py` passes 600 lines.** Split to `expressions/_lark_closures.py` with the CODEMAP row, as section 5 says.
- **simpleeval internals change.** Reusing one evaluator and setting `names` and `functions` relies on attributes simpleeval documents. The signature pin (S3) and A10 catch a change on upgrade.
- **The refusal breaks a working config.** A config that sums a CSV column today writes a concatenated string into every row, which is wrong output. The refusal names the fix (declare the type). The owner chose a coded refusal.

## 12. Follow-ups (not this plan)

- DERIVED-ARROW (1.0.x): a typed Arrow compile for a subset of `derived`, which gives it a plan-time type so it can leave the oracle and join the chunked lane. The closures from S1 stay as the fallback and as the differential oracle.
- WHOLE-COLUMN-PREPASS (1.0.x): chunks `derived_aggregate`, with an exactly rounded sum named as a byte change.
