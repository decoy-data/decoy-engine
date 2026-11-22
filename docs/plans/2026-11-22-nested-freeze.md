Status: plan (revision 1, 2026-11-22; not yet reviewed)

# NESTED-FREEZE: a closed JSONPath subset for `nested`, and a refusal for native nested columns

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: NESTED-FREEZE (group connect, 1.0), added by the owner on 2026-11-22 from the V2-to-V1 evaluation (vault `10_Projects/decoy/V2-TO-V1-EVALUATION-2026-11-22.md`, ranks 2 and 4). Two slices: (a) path grammar, (b) native nested refusal. They are independent and can land in either order.

Anchors: engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN), `profiles/local-operations.md`, `risk-and-exceptions.md`, `feature-dev.md`, `bugfix.md`, `api-and-compatibility.md`, `cross-cutting-concerns.md`, `architecture.md`, `testing.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `security.md` (value-free messages), `documentation.md`, `workspace-and-vcs.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where Things Go").

Risk: R2 (a frozen config grammar and a fail-closed refusal). Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

## 1. Frame

**(a) Grammar.** `nested.provider_config.target` is passed to `jsonpath_ng.parse` at run time (`execution/_strategies/nested/_handler.py:283`). Nothing checks it at compile. So 1.0 would freeze whatever jsonpath-ng 1.8.0 accepts. A probe on the Dell node (jsonpath-ng 1.8.0) showed that it accepts many forms that are not RFC 9535, or that mean something else there:

| Expression | jsonpath-ng 1.8.0 | RFC 9535 |
|---|---|---|
| `a.b` (no `$`) | accepted | invalid |
| `$.'b c'` | accepted, field `b c` | invalid (use `$['b c']`) |
| `$.a \| $.b` | accepted, odd result (`[2]`) | invalid |
| `` $.a.`this` `` | accepted | invalid |
| `$[0,1]` | accepted, `KeyError` on an object | valid (two selectors) |
| `$['*']` | `Fields('*')`, a wildcard | the member named `*` |
| `$.a[::-1]` | reverse order | valid, reverse order |
| `$..a` | descendants | valid (descendant segment) |
| `$.a[?(@.b)]` | lexer error (base parser) | valid (filter) |

Survey of targets in use (engine tests, docs, examples, testflight; CLI repo; platform repo; decoy-web-docs): every shipped doc and example has none. CLI and platform tests use only `$.x`, `$.user.email`, `$.user.field`, `$.nonexistent`. Engine tests also use `$`, `$.*`, `$[*]`, `$.dates[*]`, `$.items[*].k`, `$[0:1]`, `$.wrapper[:]`, `$.x[` (invalid on purpose). The subset breaks only these engine unit tests:

- `tests/unit/execution/test_nested_strategy.py`: `TestJsonPathOverlapSecurity` (`$..*`, `$..ssn` twice), `test_overlap_warning_fields` (`$..*`), `test_backtick_this_root_target_masks_whole_cell` (`` `this` ``).
- `tests/unit/execution/test_nested_strategy_strict_json.py:185` (`$..a` in the depth test).

Found while probing: `$[0]` on a JSON object cell raises a bare `KeyError: 0` from the handler (no code). The existing array-selector guard (`TestArraySelectorOnObjectFailsClosed`) covers `[*]` and slices only. Slice (a) fixes it.

**(b) Native nested columns.** What happens today (read from the code, then one probe run through `vm-run` on a plain run, companion absent):

| Column type | `redact` | `truncate` (length 2) | `nested` `$.a` | `nested` `$[0]` |
|---|---|---|---|---|
| struct | runs; type becomes string | runs; writes `{'` (Python repr of the dict) | runs; writes JSON text, type becomes string | bare `KeyError` |
| list | runs; type becomes string | runs; writes `['` | bare `ValueError` (numpy truth value) | bare `ValueError` |
| map | runs; type becomes string | runs; writes `[[` | bare `ValueError` | bare `ValueError` |

So it does not fail closed. `truncate` with a longer length writes the source values as Python repr text (a leak). `nested` reads a struct cell because `read_cell` uses any non-string cell as it is (`_leaves.py:68`). No reason code exists for this case. `hash` and `faker` were not reached in the probe (the probe config had no key and a wrong provider name); they get the same refusal.

## 2. Established solutions

Search run: RFC 9535 (JSONPath, February 2024) and the JSONPath Compliance Test Suite (`github.com/jsonpath-standard/jsonpath-compliance-test-suite`, `cts.json`); Python implementations (jsonpath-ng, the `jsonpath-rfc9535` package, `python-jsonpath`); competitor per-path masking (Tonic "Document View", Delphix Document Store masking); pyarrow nested type predicates.

- The grammar follows RFC 9535 section 2: root `$` (2.2), child segment (2.5.1), name selector (2.3.1) in shorthand and bracket form, wildcard (2.3.2), index (2.3.3), slice (2.3.4). It leaves out descendant segments (2.5.2), filters (2.3.5), function extensions (2.4) and more than one selector in a bracket. The roadmap note for X-02 (CLI `docs/roadmap/v2-v3-expansion-candidates.md:117`) already named this subset.
- jsonpath-ng stays as the evaluator. The engine builds its AST nodes (`Root`, `Child`, `Fields`, `Index`, `Slice`) from the parsed segments, so its parser is never on the public surface. Switching to an RFC 9535 library (`jsonpath-rfc9535`) was considered: it adds a dependency and changes the evaluator and writeback at freeze time. Rejected for V1; it stays an option for 1.x.
- The grammar check is about 100 lines of custom code. No maintained Python library offers "validate against a named RFC 9535 subset". The CTS gives the accepted and refused cases, so the custom part is tested against the standard's own vectors.
- (b) uses the engine's existing `contracts/column_shape.is_nested_type` (pyarrow `is_list`, `is_large_list`, `is_fixed_size_list`, `is_struct`, `is_map`, `is_union`). Refusing until per-path masking of native nested types exists matches the fail-closed rule in the V1 threat model.

### Reuse inventory

- `_nested_json.nested_children` (`src/decoy_engine/_nested_json/_rules.py:40`): the one reader of the child config; both checks read `target` through it.
- `contracts/column_shape.is_nested_type` (`src/decoy_engine/contracts/column_shape.py:103`): the one nested-type predicate.
- `SourceFacts.schemas` (`src/decoy_engine/contracts/column_shape.py:66`): the source schemas every compile route already passes to `compile_plan`.
- `plan/checks/_generate_columns._located`: the located `PlanCompileError` builder `_text_mask_strategy.py` already uses.
- `SCALAR_HANDLERS` (`src/decoy_engine/execution/_strategies/__init__.py:52`): the strategy registry the guard test walks.

## 3. Guarantee and non-goals

**(a)** After this slice:

1. A `nested` target compiles only when it matches this grammar (no blank space anywhere outside a quoted name):
   - `target = "$" *segment`
   - `segment = "." name / ".*" / "[" selector "]"`
   - `name` = RFC 9535 `member-name-shorthand`
   - `selector` = a quoted name (single or double quotes, RFC 9535 escapes) / `*` / an index (an integer, may be negative, no leading zero, not `-0`, within plus or minus 2^53 - 1) / a slice `[start]:[end][:step]` where `step`, if given, is a whole number of 1 or more.
2. A quoted name `*` (`$['*']`) is refused, because jsonpath-ng would read it as a wildcard. Everything else outside the grammar is refused: `..`, filters, `,` unions, a missing `$`, dot-quoted names, jsonpath-ng extensions (`|`, `where`, `&`, backticks), a step of 0 or less.
3. The check runs in `compile_plan` and in `run_config_only_checks`, so `decoy run` and `decoy validate` refuse the same configs, with `plan.nested_target_unsupported`. The message names table, column, config path, the character position and the form found. It may show the target (config text, up to 64 characters), never a cell.
4. Every accepted target selects what RFC 9535 says it selects.
5. The handler gets its expression from the one grammar function. Nothing in `src/` calls `jsonpath_ng.parse`.
6. An index selector on an object cell fails closed with `nested_target_unwritable_container`, like `[*]` does today.

**(b)** After this slice, a mask table column whose source Arrow type is nested (`is_nested_type`) and whose strategy is anything other than `passthrough` is refused in `compile_plan` with `plan.native_nested_column_unsupported`, before any data row is read, on every run route (plain, auto-chunked, `run_mask_pipeline_chunked`, multi-table). This includes `nested`, which today half works on a struct. A strategy added later is refused by default. An untargeted or `passthrough` nested column keeps the behavior engine #754 gave it.

Non-goals: masking inside native nested columns (NESTED-NATIVE, 1.x); JSON and JSONL files (X-02, 1.x); widening the grammar (additive in 1.x); `decoy validate` with no source schema (it cannot see the type; `decoy run` refuses); generate tables; retiring the `nested_jsonpath_path_overlap` warning code, which becomes unreachable from a compiled plan (recorded as a follow-up).

## 4. Enumerations

### Exit paths

- Grammar refusal: `PlanCompileError` from the new check, before any read.
- Handler backstop: `StrategyError(nested_jsonpath_parse_error)` at `src/decoy_engine/execution/_strategies/nested/_handler.py:283`, reached only when the handler runs without a compiled plan.
- Index on object: `StrategyError(nested_target_unwritable_container)` from `find_matches` (`src/decoy_engine/execution/_strategies/nested/_leaves.py:42`).
- Native nested refusal: `PlanCompileError` from the new check in `compile_plan`.

### Routes

- `compile_plan` (`src/decoy_engine/plan/_compile.py:123`): both checks; every run route compiles here first (plain, auto-chunked, `run_mask_pipeline_chunked`, multi-table, native companion).
- `run_config_only_checks` (`src/decoy_engine/plan/_compile.py:486`): grammar check only; it has no source schema.

### FK shapes

N/A: neither check reads keys or relationships; a nested column used as a key is refused like any other targeted nested column.

### Fields

- `provider_config.target` of a `nested` column (single form; `nested_children` returns one child today).
- The source Arrow type of every column entry in a mask table.

### Output surfaces

- Reason codes and messages: config path and target text only, no cell value.
- Masked output: unchanged for accepted targets; refused jobs write nothing.

## 5. Slices and size

(a): 1 new foundation module (about 120 lines), 1 new plan check (about 50), edits to `_nested_json/__init__.py`, `plan/checks/__init__.py`, `plan/_compile.py` (2 call lines, net zero lines; see below), `_handler.py` (net shrink), `_leaves.py` (about 5 lines), the plan reason catalog, 1 sentry, tests, a changelog fragment, `docs/compatibility-contract.md`. New public names: none. New reason code: `nested_target_unsupported`.

(b): 1 new plan check (about 50 lines), `plan/checks/__init__.py`, `plan/_compile.py` (1 call line, net zero), the plan reason catalog, tests, a changelog fragment, `docs/compatibility-contract.md`. New public names: none. New reason code: `native_nested_column_unsupported`.

`plan/_compile.py` is at its exact size ceiling (674, `tests/sentry/test_module_size.py:110`) and may only shrink. Each new call line pays for itself by removing a stale narrative comment line in the same function.

## 6. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `_target.py` (`parse_target`, `TargetPath`, `to_jsonpath`) | `src/decoy_engine/_nested_json/` | "Nested JSON cell foundation" | `_rules.py` (`nested_children`) |
| `_nested_target.py` | `src/decoy_engine/plan/checks/` | "Plan compile and checks": new checks in `plan/checks/_<topic>.py` | `_text_mask_strategy.py` |
| `_native_nested_columns.py` | `src/decoy_engine/plan/checks/` | same | `_column_shapes.py` |
| `test_nested_target_choke_point.py` | `tests/sentry/defects/` | "Sentry test": recurring-defect class rules | `test_nested_child_choke_point.py` |
| `test_target_grammar.py`, `cts_subset.json` | `tests/unit/nested_json/` | "Unit tests" mirroring `src/` | existing `tests/unit/nested_json/` |
| `test_nested_target_check.py`, `test_native_nested_columns.py` | `tests/unit/plan/checks/` | "Unit tests" mirroring `src/` | the existing tests in that folder |

`plan/checks/` has 11 modules, under its fan-out limit. `_nested_json` stays in the bottom layer: it imports jsonpath-ng and the standard library, not `reasons`; it raises its own `TargetSyntaxError(position, form)` and the callers map it to a code.

## 7. Choke points

- (a) One grammar: `_nested_json.parse_target`. The plan check and the handler both call it. Guard: `tests/sentry/defects/test_nested_target_choke_point.py` walks the AST of every module under `src/` and fails on a call to `jsonpath_ng.parse` or `jsonpath_ng.ext.parse`, or an import of either. Mutation that must turn it red: put `jsonpath_ng.parse(target_path)` back in `_handler.py`.
- (b) One rule: `_native_nested_columns.ALLOWED_ON_NATIVE_NESTED = frozenset({"passthrough"})`, applied to every column entry of every mask table. Guard: a test parametrized over `SCALAR_HANDLERS` keys minus that set (read from the registry, never a hand list) asserts each is refused on a struct, a list and a map. Mutation: add `"redact"` to the set; the guard must go red.

## 8. Acceptance tests (each fails before the change)

Slice (a):

- **A1 grammar table.** About 25 accepted forms (`$`, `$.a`, `$['a']`, `$["a b"]`, `$.*`, `$[*]`, `$[0]`, `$[-1]`, `$[1:]`, `$[0:4:2]`, `$.users[*].email`) compile. About 20 refused forms (`$..a`, `$..*`, `a.b`, `$.'b c'`, `$.a | $.b`, `` `this` ``, `$[0,1]`, `$['a','b']`, `$[?(@.b)]`, `$['*']`, `$[::-1]`, `$[::0]`, `$[01]`, `$[-0]`, `$ .a`, `$.x[`) each fail `compile_plan` and `run_config_only_checks` with `nested_target_unsupported`. Fail-before: no compile check exists, so all of them compile.
- **A2 CTS parity.** `cts_subset.json` holds the CTS cases whose selector is in the subset, plus all its `invalid_selector` cases, with the source commit and licence noted in the file. Each valid case gives the CTS result through `to_jsonpath(parse_target(...)).find`. Each invalid case is refused. If the CTS licence does not allow a copy, the builder hand-writes the cases from the RFC 9535 examples (tables 2 to 8) and cites them.
- **A3** `$['*']` on `{"*": 1, "a": 2}`: refused. Fail-before: jsonpath-ng selects both members.
- **A4** `$[0]` on the object cell `{"a": "SSN-1"}`: `StrategyError` with `nested_target_unwritable_container`, and the message does not hold the cell text. Fail-before: bare `KeyError`.
- **A5** The six breaking tests in section 1 are rewritten: the `$..ssn` masking tests use `$.*.ssn`; the depth test builds an explicit `$.a.a...` path; `` `this` `` becomes a refusal test; the overlap tests call the overlap helper directly with built matches. Every other nested test passes unchanged.
- **A6** The choke-point sentry and its mutation (section 6).

Slice (b):

- **B1** For each of struct, list, large list, fixed-size list and map (Parquet source) and union (resident table only, Parquet cannot hold it), and each strategy in `SCALAR_HANDLERS` other than `passthrough` with an otherwise valid config: `compile_plan` raises `native_nested_column_unsupported`. The message names the table, the column and the type family, and no cell value. Fail-before: the probe table above.
- **B2 truncate leak.** A struct column with `truncate` length 20 is refused. Fail-before: the output holds the repr of the source dict.
- **B3 routes.** `run_pipeline` (plain and auto-chunked) and `run_mask_pipeline_chunked` refuse with the same code and write no output. The companion-present CI job runs the same test.
- **B4 passthrough unchanged.** `tests/native/test_unconfigured_passthrough_types.py` (#754) passes unchanged. One added case lists the struct column explicitly as `passthrough` and gets the source type back.
- **B5** A nested-typed column under a `when:` gate is refused the same way.

## 9. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | refusal messages; the index-on-object error | messages hold config path, target text and type family only | A4, B1 message asserts | put the cell repr in the B1 message |
| 2 | Cleanup missing on an exit path | none | N/A: both refusals happen at compile, before anything is opened or staged | B3 (no output written) | n/a |
| 3 | State and concurrency | none | N/A: pure functions over config and schema, no shared state | n/a | n/a |
| 4 | Route parity and silent fallback | plain, chunked, multi-table, native routes; `decoy validate` | both checks in `compile_plan`, which every route calls; grammar also in `run_config_only_checks` | A1, B3 | drop the call from `compile_plan` (B3 red) |
| 5 | Referential integrity | none | N/A: no key or FK logic touched | n/a | n/a |
| 6 | Untrusted producer | a hand-written target string | strict grammar, refuse anything outside it | A1, A2, A3 | accept `..` in `parse_target` (A1 red) |
| 7 | Check then use (TOCTOU) | grammar checked at compile, used at run | the handler parses with the same `parse_target`, never with `jsonpath_ng.parse` | A6 sentry | call `jsonpath_ng.parse` in the handler (A6 red) |
| 8 | Weak tests | grammar tests that only test acceptance | refused forms assert the code; CTS valid cases assert results | A1, A2 | make `parse_target` accept everything (A1 red) |
| 9 | Refactor drift | handler rewritten to use built AST | existing nested tests on subset targets pass unchanged | A5 | build `Fields` for `[*]` (array tests red) |
| 10 | Frozen contract drift | `nested.target` grammar; reason catalog | grammar and codes listed in `docs/compatibility-contract.md`; reason registry sentries | A1, reason sentries | rename a new code (registry sentry red) |

## 10. Frozen contracts and compatibility

- Breaking before 1.0, on purpose: a target outside the subset that compiled before is now refused at compile, and a native nested column with a mask rule that ran before is now refused. No shipped doc, example, CLI or platform config uses either. Each slice adds a changelog fragment with a `Breaking:` line.
- After 1.0, the subset is the frozen grammar of `nested.target`. Adding `..`, filters or unions later is additive in 1.x. `docs/compatibility-contract.md` lists the grammar and the two new reason codes as frozen.
- `nested_jsonpath_parse_error` (runtime) stays: it is the handler backstop when the handler is called without a compiled plan. `nested_jsonpath_path_overlap` stays registered, unreachable from a compiled plan; retiring it is a follow-up.
- CLI: no code change. The new codes reach `decoy explain` through the engine reason registry. CLI tests use only subset targets.

## 11. Pre-mortem

- A user config with `$..ssn` stops compiling. Accepted before 1.0; the refusal names the form and the fix (`$.*.ssn` or an explicit path). No shipped doc or example uses it.
- A run route compiles without the source schema, so (b) misses it. B3 covers each route; a route with no schema for a table is a bug found by B3, not a silent pass.
- jsonpath-ng changes its AST classes in a later version. The built AST would then break loudly in A2; the pin is a ceiling.
- The CTS copy is not allowed by its licence. Fallback is in A2.

## 12. Open questions for the owner

- Q1. A `nested` rule on a native struct column runs today and writes JSON text in place of the struct (the type changes). This plan refuses it until NESTED-NATIVE. Recommended: refuse. The other choice keeps it and documents the type change, which then freezes the JSON-text output.
