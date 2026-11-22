Status: plan (revision 2, 2026-11-22; Dennis round 1 applied, owner decision Q1 recorded)

# NESTED-FREEZE: a closed JSONPath subset for `nested`, and a refusal for native nested columns

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: NESTED-FREEZE (group connect, 1.0), added by the owner on 2026-11-22 from the V2-to-V1 evaluation (vault `10_Projects/decoy/V2-TO-V1-EVALUATION-2026-11-22.md`, ranks 2 and 4). Two slices: (a) path grammar, (b) native nested refusal. They are independent and can land in either order.

Anchors: engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN), `profiles/local-operations.md`, `risk-and-exceptions.md`, `feature-dev.md`, `bugfix.md`, `api-and-compatibility.md`, `cross-cutting-concerns.md`, `architecture.md`, `testing.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `security.md` (value-free messages), `documentation.md`, `workspace-and-vcs.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where Things Go").

Risk: R2 (a frozen config grammar and a fail-closed refusal). Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

Owner decision (Q1, Cam, 2026-11-22): refuse any rule other than `passthrough` on a native nested column until NESTED-NATIVE ships in 1.x. This includes `nested` on a struct, which runs today and writes JSON text. Slice (b) carries the decision.

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
- `SCALAR_HANDLERS` (`src/decoy_engine/execution/_strategies/__init__.py:52`): the handler registry; the guard asserts every key is in the walked set.
- `support/_shape.StrategyKind` (`src/decoy_engine/support/_shape.py:129`): every mask strategy name, `from_parent` included; the guard walks it.
- `execution/_column_access.column_access` (`src/decoy_engine/execution/_column_access.py:362`): the one registry of the columns an entry reads and writes; (b) reads references only through it.

## 3. Guarantee and non-goals

**(a)** After this slice:

1. A `nested` target compiles only when the whole string matches this grammar (`re.fullmatch` semantics on the full text: no leading or trailing blank space, no trailing newline, no blank space anywhere outside a quoted name):
   - `target = "$" *segment`
   - `segment = "." name / ".*" / "[" selector "]"`
   - `name` = RFC 9535 `member-name-shorthand`
   - `selector` = a quoted name (single or double quotes, RFC 9535 escapes) / `*` / an index (an integer, may be negative, no leading zero, not `-0`, within plus or minus 2^53 - 1) / a slice `[start]:[end][:step]` where `step`, if given, is a whole number of 1 or more.
2. A quoted name `*` (`$['*']`) is refused, because jsonpath-ng would read it as a wildcard. Everything else outside the grammar is refused: `..`, filters, `,` unions, a missing `$`, dot-quoted names, jsonpath-ng extensions (`|`, `where`, `&`, backticks), a step of 0 or less.
3. The check runs in `compile_plan` and in `run_config_only_checks`, so `decoy run` and `decoy validate` refuse the same configs, with `plan.nested_target_unsupported`. The message names table, column, config path, the character position and the form found. It may show the target (config text, up to 64 characters). A longer target is cut at 64 characters and the message says so (`target (first 64 of N characters): ...`). It never shows a cell.
4. Every accepted target selects what RFC 9535 selects, or fails closed with a coded error. It never selects something else. The fail-closed cases are the ones where the handler cannot write back what RFC 9535 selects: an index, slice or wildcard-on-array selector on an object cell (guarantee 6, A4, `TestArraySelectorOnObjectFailsClosed`), where RFC 9535 selects nothing and jsonpath-ng raises or selects members.
5. The handler gets its expression from the one grammar function. Nothing in `src/` calls `jsonpath_ng.parse`.
6. An index selector on an object cell fails closed with `nested_target_unwritable_container`, like `[*]` does today.

**(b)** After this slice, a mask table column whose Arrow type is nested (`is_nested_type`) is refused with `runtime.native_nested_column_unsupported` when any rule other than `passthrough` touches it. One code, two raise sites, one rule module (`execution/_native_nested_guard.py`):

1. **Touches** means the column is in the entry's own target, or in what `execution/_column_access.column_access(entry, registry)` (`src/decoy_engine/execution/_column_access.py:362`) says the entry reads or writes. That registry already covers `joint_mask` `columns` and `key_by` (`_column_access.py:173`, `_strategies/_joint_mask.py:58`), `derived` and `formula` references (`:154`), the sibling keys `group_by`, `order_by`, `anchor` and `reference_column` (`:43`) and `when:` predicate names (`:196`). No second reader of those keys is written. An entry with `reads_unknown` or `writes_unknown` in a table that has a nested column is refused (fail closed: the guard cannot prove the entry leaves the column alone).
2. **Static site.** `refuse_native_nested_columns(config, schemas, registry)` runs in `build_run_context` (`src/decoy_engine/execution/_pipeline_context.py:176`), beside `_guards.refuse_dropped_declared_tables` (`:380`), after the compiled plan exists and before any source row is read. It reads the Arrow type from `SourceFacts.schemas` and the loader schemas (`:300`).
3. **Unknown schema.** A table whose Arrow schema is not known before the read (a lazy or descriptor source with no schema at `_pipeline_context.py:300` and `:380`, or a direct `PandasAdapter` call with a hand-built, uncompiled `Plan`) is not let through. The runtime site refuses it.
4. **Runtime site (backstop).** `refuse_native_nested_cells(df, seed, registry, table)` runs before `handler.run` at every pandas dispatch: `run_with_when_gate` (`src/decoy_engine/execution/_when_gate.py:434`, both the plain and the gated branch, before `preflight`), the composite branch of `_pandas_adapter._dispatch_mask_node`, and the orphan REMAP closure (`src/decoy_engine/execution/_strategies/_orphan.py:151`). It builds the touched set with the same `column_access` from the seed's strategy, `provider_config` and `when`. For each touched column of object dtype it refuses on the first non-null cell that is a `dict`, `list`, `tuple` or `numpy.ndarray` (the pandas forms of Arrow struct, list and map). It checks types only and never puts a value in the message.
5. The estimate route (`src/decoy_engine/execution/_job_estimate.py:157`, `NO_SOURCES`) masks nothing and reads no rows, so it does not refuse. Its estimate is not a promise that the run compiles.
6. Every strategy name is refused except `passthrough` (`ALLOWED_ON_NATIVE_NESTED = frozenset({"passthrough"})`), so a strategy added later is refused by default. An untargeted or `passthrough` nested column that no other entry touches keeps the behavior engine #754 gave it.

Decisions per reference kind (each has a B8 test):

| Reference | Decision | Why |
|---|---|---|
| own target, any strategy but `passthrough` | refuse | owner Q1 |
| `joint_mask` `columns` member | refuse | it writes the column |
| `joint_mask` `key_by` | refuse | the HMAC key would hash a Python repr |
| `derived` or `formula` expression name | refuse | numexpr and the derived parser cannot read a struct |
| `group_by`, `order_by`, `anchor`, `reference_column` | refuse | a dict or array is not a stable group or sort key |
| `when:` predicate name | refuse | the predicate would compare a container |
| `from_parent` (FK wiring) | refuse | it is a strategy name other than `passthrough` |
| not touched by any entry | allow | #754 carries it through unchanged |

Non-goals: masking inside native nested columns (NESTED-NATIVE, 1.x); JSON and JSONL files (X-02, 1.x); widening the grammar (additive in 1.x); `decoy validate` (it reads no source schema, so it cannot see the type; `decoy run` refuses); generate tables; retiring the `nested_jsonpath_path_overlap` warning code from the registry, which becomes unreachable (recorded as a follow-up).

## 4. Enumerations

### Exit paths

- Grammar refusal: `PlanCompileError` from the new check, before any read.
- Handler backstop: `StrategyError(nested_jsonpath_parse_error)` at `src/decoy_engine/execution/_strategies/nested/_handler.py:283`, reached only when the handler runs without a compiled plan.
- Index on object: `StrategyError(nested_target_unwritable_container)` from `find_matches` (`src/decoy_engine/execution/_strategies/nested/_leaves.py:42`).
- Native nested refusal, static: `ExecutionError(native_nested_column_unsupported)` from `build_run_context`, before any read.
- Native nested refusal, runtime: the same code from the dispatch backstop, before the handler writes. On a chunked route this can be after earlier tables or chunks were staged; the existing failure path removes staged output (B6 asserts no final output).

### Routes

- `compile_plan` (`src/decoy_engine/plan/_compile.py:123`): grammar check; every run route compiles here first (plain, auto-chunked, `run_mask_pipeline_chunked`, multi-table, native companion).
- `run_config_only_checks` (`src/decoy_engine/plan/_compile.py:486`): grammar check only; it has no source schema.
- `build_run_context` (`src/decoy_engine/execution/_pipeline_context.py:176`): native nested static check, for tables with a known schema.
- Pandas dispatch (`_when_gate.py:434`, `_dispatch_mask_node` composite branch, `_orphan.py:151`): native nested runtime backstop, for every table, schema known or not.
- Job estimate (`_job_estimate.py:157`): no check; it reads no rows.

### FK shapes

- A nested column named as a `joint_mask` `key_by`: refused by (b) (section 3 table, B8).
- A nested column wired by `from_parent` or used as an orphan REMAP parent column: refused by (b) (B7, B8).
- The grammar check (a) reads no keys or relationships.

### Fields

- `provider_config.target` of a `nested` column (single form; `nested_children` returns one child today).
- The Arrow type of every column a mask table entry touches: own target, `column_access` reads and writes (`joint_mask` `columns` and `key_by`, `derived` and `formula` names, `group_by`, `order_by`, `anchor`, `reference_column`, `when:` names).

### Output surfaces

- Reason codes and messages: config path and target text only, no cell value.
- Masked output: unchanged for accepted targets; refused jobs write nothing.

## 5. Slices and size

(a): 1 new foundation module (about 120 lines), 1 new plan check (about 50), edits to `_nested_json/__init__.py`, `plan/checks/__init__.py`, `plan/_compile.py` (2 call lines, net zero lines; see below), `_handler.py` (net shrink), `_leaves.py` (about 5 lines), the plan reason catalog, 1 sentry, tests, a changelog fragment, `docs/compatibility-contract.md`. New public names: none. New reason code: `nested_target_unsupported`.

(b): 1 new execution module (about 90 lines), 1 call line each in `_pipeline_context.py`, `_when_gate.py` (2), `_pandas_adapter.py` and `_orphan.py`, the runtime reason catalog, tests, a changelog fragment, `docs/compatibility-contract.md`. New public names: none. New reason code: `runtime.native_nested_column_unsupported`. `plan/_compile.py` is not touched by (b).

The runtime backstop costs one type check per non-null cell of each touched object-dtype column per dispatch, and stops at the first nested cell. Strings are the common case. The builder measures it on the 1M-row prodsim table; if it adds more than 2% to the run, it checks the first non-null cell plus `Series.map(type).nunique()` instead, and records the number.

`plan/_compile.py` is at its exact size ceiling (674, `tests/sentry/test_module_size.py:110`) and may only shrink. Each new (a) call line pays for itself by removing a stale narrative comment line in the same function.

(a) also touches the dependency spec: `pyproject.toml:100` changes from `jsonpath-ng>=1.6` to `jsonpath-ng>=1.8.0,<2` (the built-AST code uses the 1.8.0 `Index(*indices)`, `Slice(start, end, step)` and `Fields(*fields)` signatures, the version the lock and the CTS run use), and `uv.lock` is regenerated (its resolved version stays 1.8.0; only the specifier line changes). A dependency lock change is a full-suite trigger (testing.md escalation list), so the (a) merge head runs the full suite against the saved main baseline.

## 6. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `_target.py` (`parse_target`, `TargetPath`, `to_jsonpath`) | `src/decoy_engine/_nested_json/` | "Nested JSON cell foundation" | `_rules.py` (`nested_children`) |
| `_nested_target.py` | `src/decoy_engine/plan/checks/` | "Plan compile and checks": new checks in `plan/checks/_<topic>.py` | `_text_mask_strategy.py` |
| `_native_nested_guard.py` | `src/decoy_engine/execution/` | "Execution guards" at the dispatch choke point | `_gated_string_guard.py` (`require_same_rows`) |
| `test_nested_target_choke_point.py` | `tests/sentry/defects/` | "Sentry test": recurring-defect class rules | `test_nested_child_choke_point.py` |
| `test_target_grammar.py`, `cts_subset.json` | `tests/unit/nested_json/` | "Unit tests" mirroring `src/` | existing `tests/unit/nested_json/` |
| `test_nested_target_check.py` | `tests/unit/plan/checks/` | "Unit tests" mirroring `src/` | the existing tests in that folder |
| `test_native_nested_guard.py` | `tests/unit/execution/` | "Unit tests" mirroring `src/` | `test_nested_strategy.py` |
| `test_native_nested_routes.py` | `tests/native/` | route parity tests | `test_unconfigured_passthrough_types.py` |

`plan/checks/` has 11 modules, under its fan-out limit. `src/decoy_engine/execution` is at 103 against its fan-out limit (`tests/sentry/layout/test_package_fanout.py:32`); if the new module crosses it, the two functions go into `_gated_string_guard.py` (126 lines) instead, with no new module. The guard must sit in `execution`, not `plan/checks`: it reuses `execution/_column_access.column_access`, and `plan` is below `execution` in `.importlinter`. `_nested_json` stays in the bottom layer: it imports jsonpath-ng and the standard library, not `reasons`; it raises its own `TargetSyntaxError(position, form)` and the callers map it to a code.

## 7. Choke points

- (a) One grammar: `_nested_json.parse_target`. The plan check and the handler both call it. Guard: `tests/sentry/defects/test_nested_target_choke_point.py` walks the AST of every module under `src/`. It fails on any import of `jsonpath_ng.parser`, `jsonpath_ng.lexer` or `jsonpath_ng.ext` (or anything under it), on any import of the names `parse`, `JsonPathParser` or `JsonPathLexer` from `jsonpath_ng` (with or without `as`), and on any attribute access `.parse` or `.JsonPathParser` on a name bound to the `jsonpath_ng` module (alias-aware: it tracks `import jsonpath_ng as jp`). The one allowed importer of `jsonpath_ng.jsonpath` AST classes is `_nested_json/_target.py`. Mutations that must turn it red: put `jsonpath_ng.parse(target_path)` back in `_handler.py`; add `import jsonpath_ng as jp; jp.parse(...)`; add `from jsonpath_ng.ext import parse as p`.
- (b) One rule: `_native_nested_guard.ALLOWED_ON_NATIVE_NESTED = frozenset({"passthrough"})`, applied by both raise sites to every column an entry touches. Guard: a test parametrized over every mask strategy name, read from `support/_shape.StrategyKind` (`src/decoy_engine/support/_shape.py:129`, mask strategies plus `from_parent`, `:144`) minus the generate-only kinds and minus the allow set. It also asserts `set(SCALAR_HANDLERS) | {"from_parent"}` is inside the walked set, so a new handler or a new dispatch branch cannot be skipped. Each name is refused on a struct, a list and a map. Mutation: add `"redact"` to the allow set; the guard must go red.

## 8. Acceptance tests (each fails before the change)

Slice (a):

- **A1 grammar table.** About 25 accepted forms (`$`, `$.a`, `$['a']`, `$["a b"]`, `$.*`, `$[*]`, `$[0]`, `$[-1]`, `$[1:]`, `$[0:4:2]`, `$.users[*].email`) compile. About 20 refused forms (`$..a`, `$..*`, `a.b`, `$.'b c'`, `$.a | $.b`, `` `this` ``, `$[0,1]`, `$['a','b']`, `$[?(@.b)]`, `$['*']`, `$[::-1]`, `$[::0]`, `$[01]`, `$[-0]`, `$ .a`, `$.x[`, `"$.a\n"` (trailing newline), `" $.a"`, `"$.a "`, `"$.a\t"`) each fail `compile_plan` and `run_config_only_checks` with `nested_target_unsupported`. Fail-before: no compile check exists, so all of them compile.
- **A2 CTS parity.** `cts_subset.json` holds the CTS cases whose selector is in the subset, plus all its `invalid_selector` cases, with the source commit and licence noted in the file. Each valid case gives the CTS result through `to_jsonpath(parse_target(...)).find`. Each invalid case is refused. The test names each CTS case it runs (the CTS `name` field is the pytest id), and the plan pins these groups by CTS name: `basic, root`, `basic, name shorthand`, `basic, name shorthand, ...` (all), `basic, wildcard shorthand, ...`, `basic, multiple selectors, ...` (refused), `basic, descendant segment, ...` (refused), `name selector, double quotes, ...` and `name selector, single quotes, ...` (all escape cases), `index selector, ...` (all), `slice selector, ...` with a step of 1 or more, `slice selector, negative step, ...` and `slice selector, step, zero` (refused), `filter, ...` (refused). A CTS valid case on an object document whose selector is index, slice or wildcard is expected to fail closed with `nested_target_unwritable_container` (guarantee 4); the fixture marks each such case by name and the test asserts the code, not the CTS result. If the CTS licence does not allow a copy, the builder hand-writes the cases from the RFC 9535 examples (tables 2 to 8) and cites them.
- **A3** `$['*']` on `{"*": 1, "a": 2}`: refused. Fail-before: jsonpath-ng selects both members.
- **A4** `$[0]` on the object cell `{"a": "SSN-1"}`: `StrategyError` with `nested_target_unwritable_container`, and the message does not hold the cell text. Fail-before: bare `KeyError`.
- **A5** The six breaking tests in section 1 are rewritten: the `$..ssn` masking tests use `$.*.ssn`; the depth test builds an explicit `$.a.a...` path; `` `this` `` becomes a refusal test. The overlap security cases (`TestJsonPathOverlapSecurity`, `test_overlap_warning_fields`) become refusal tests: `$..*` and `$..ssn` fail compile with `nested_target_unsupported`. No subset target can make overlapping matches (no descendant segment, one selector per bracket), so `_has_prefix_overlap` (`_handler.py:573`) and its call (`:360`) are deleted, not kept as dead helpers. Every other nested test passes unchanged.
- **A7 long target.** A refused 200-character target gives a message with the first 64 characters and `first 64 of 200 characters`.
- **A6** The choke-point sentry and its mutation (section 6).

Slice (b):

- **B1** For each of struct, list, large list, fixed-size list and map (Parquet source) and union (resident table only, Parquet cannot hold it), and each mask strategy name from the section 7 guard with an otherwise valid config: `run_pipeline` raises `native_nested_column_unsupported` from the static site, before any read. The message names the table, the column and the type family, and no cell value. Fail-before: the probe table above.
- **B2 truncate leak.** A struct column with `truncate` length 20 is refused. Fail-before: the output holds the repr of the source dict.
- **B3 routes.** `run_pipeline` (plain and auto-chunked) and `run_mask_pipeline_chunked` refuse with the same code and write no output. The companion-present CI job runs the same test.
- **B4 passthrough unchanged.** `tests/native/test_unconfigured_passthrough_types.py` (#754) passes unchanged. One added case lists the struct column explicitly as `passthrough` and gets the source type back.
- **B5** A nested-typed column under a `when:` gate is refused the same way.
- **B6 unknown schema.** A table given through a lazy source loader with no schema before the read, struct column masked with `redact`: the runtime site refuses with the same code, and no final output file exists. Fail-before: the column is written as a string.
- **B7 uncompiled plan.** A direct `PandasAdapter` call with a hand-built `Plan` (no `compile_plan`) and `redact` on a struct column: refused by the runtime site with the same code. A second case calls the orphan REMAP closure on a parent struct column: refused. Fail-before: both run.
- **B8 references.** One case per row of the section 3 decision table, on a struct column with the referencing entry on a scalar column: `joint_mask` with the struct in `columns`; `joint_mask` with `key_by` on the struct; `derived` naming the struct; `formula` naming the struct; `group_by` on the struct; `when:` naming the struct; `from_parent` on the struct. Each is refused by the static site and, with the schema withheld, by the runtime site. The last case (struct touched by nothing) runs and keeps the struct type. Fail-before: each runs.

## 9. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | refusal messages; the index-on-object error | messages hold config path, target text and type family only | A4, B1 message asserts | put the cell repr in the B1 message |
| 2 | Cleanup missing on an exit path | the (b) runtime site on a chunked route | the static refusal is before any read; the runtime refusal raises through the existing staged-output cleanup | B3, B6 (no final output) | swallow the error in the chunk loop (B6 red) |
| 3 | State and concurrency | none | N/A: pure functions over config and schema, no shared state | n/a | n/a |
| 4 | Route parity and silent fallback | plain, chunked, multi-table, native routes; unknown-schema tables; direct adapter calls; `decoy validate` | grammar in `compile_plan` and `run_config_only_checks`; (b) static in `build_run_context`, runtime at every pandas dispatch | A1, B3, B6, B7 | drop the runtime call from `run_with_when_gate` (B6, B7 red) |
| 5 | Referential integrity | none | N/A: no key or FK logic touched | n/a | n/a |
| 6 | Untrusted producer | a hand-written target string | strict grammar, refuse anything outside it | A1, A2, A3 | accept `..` in `parse_target` (A1 red) |
| 7 | Check then use (TOCTOU) | grammar checked at compile, used at run | the handler parses with the same `parse_target`, never with `jsonpath_ng.parse` | A6 sentry | call `jsonpath_ng.parse` in the handler (A6 red) |
| 8 | Weak tests | grammar tests that only test acceptance | refused forms assert the code; CTS valid cases assert results | A1, A2 | make `parse_target` accept everything (A1 red) |
| 9 | Refactor drift | handler rewritten to use built AST; reference reads | existing nested tests on subset targets pass unchanged; (b) reads references only through `column_access` | A5, B8 | read `key_by` by hand and skip `columns` (B8 red) |
| 10 | Frozen contract drift | `nested.target` grammar; reason catalog | grammar and codes listed in `docs/compatibility-contract.md`; reason registry sentries | A1, reason sentries | rename a new code (registry sentry red) |

## 10. Frozen contracts and compatibility

- Breaking before 1.0, on purpose: a target outside the subset that compiled before is now refused at compile, and a native nested column with a mask rule that ran before is now refused. No shipped doc, example, CLI or platform config uses either. Each slice adds a changelog fragment with a `Breaking:` line.
- Dependency: `jsonpath-ng>=1.8.0,<2` in `pyproject.toml`, lock regenerated (full-suite trigger, section 5). The engine relies on the jsonpath-ng AST classes, so a major release must be tested before the ceiling moves.
- After 1.0, the subset is the frozen grammar of `nested.target`. Adding `..`, filters or unions later is additive in 1.x. `docs/compatibility-contract.md` lists the grammar, the 64-character message cap and the two new reason codes (`plan.nested_target_unsupported`, `runtime.native_nested_column_unsupported`) as frozen.
- `nested_jsonpath_parse_error` (runtime) stays: it is the handler backstop when the handler is called without a compiled plan. `nested_jsonpath_path_overlap` stays registered and is unreachable once `_has_prefix_overlap` is deleted; retiring the code is a follow-up.
- CLI: no code change. The new codes reach `decoy explain` through the engine reason registry. CLI tests use only subset targets.

## 11. Pre-mortem

- A user config with `$..ssn` stops compiling. Accepted before 1.0; the refusal names the form and the fix (`$.*.ssn` or an explicit path). No shipped doc or example uses it.
- A run route has no source schema for a table, so the static site misses it. The runtime site refuses it at dispatch (B6, B7).
- A native route masks a nested column without pandas dispatch. The companion-present CI job runs B3 and B8; the static site runs before the route decision, so the native route never sees the column.
- jsonpath-ng changes its AST classes in a later version. The new `<2` ceiling blocks a major; a minor that changes them breaks loudly in A2.
- The CTS copy is not allowed by its licence. Fallback is in A2.

## 12. Open questions for the owner

None. Q1 (refuse `nested` and every other non-passthrough rule on a native nested column) was decided by the owner on 2026-11-22; see the header.
