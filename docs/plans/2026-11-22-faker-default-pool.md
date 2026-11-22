Status: plan (revision 2, 2026-11-22; Dennis R1 items closed)

# FAKER-DEFAULT-POOL: a `faker` column with no `pool_size` runs native and chunked, as if it declared 10,000

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: FAKER-DEFAULT-POOL (group mask, 1.0), new from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, rank 1). One slice, engine only. The CLI gets the change through its next engine pin bump; no CLI code changes.

Anchors: a path with no prefix is under `src/decoy_engine/` in this repository (decoy-engine). Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN), `risk-and-exceptions.md`, `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where things go").

Risk: R2 (masking route admission on a hot lane; a frozen-contract doc entry changes). Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

Owner direction (2026-11-22): every masking strategy runs its fastest path by default; V1 must be fast and reproducible; a byte change that buys speed or robustness is allowed before V1 if it is marked here and in the changelog `Breaking:` line. For this row the byte-identical design is also the fastest one, so the only byte change is the type of an empty or all-null output column (section 10).

## 1. Frame

The pandas oracle builds a missing `pool_size` as `DEFAULT_POOL_SIZE` = 10,000 (`generation/pool/_runtime_pool_size.py:25`, reached through `effective_pool_size`, `generation/pool/_identity.py:27`). Every native and chunked admission check refuses the same column instead, with the text "the non-chunked default of 10000 is not applied silently here". So `faker(person_first_name)` and `faker(person_last_name)`, the two providers the native operator takes, run on pandas whenever the config omits `pool_size`, and a table of 100,000 rows or more also loses chunking and runs full frame. All four CLI mask templates and 20 engine disguise rules use these providers with no `pool_size`.

The audit measured that the output does not change when the default is applied: `faker(person_first_name)` on pandas and `faker(person_first_name, pool_size: 10000)` on the native route give the same output hash at 2,000 and 120,000 rows, for first name, last name, and the deterministic form with a namespace.

Refusal sites at `70881ad79`:

| # | Site | What it refuses |
|---|---|---|
| R1 | `execution/native/_requirements.py:227` `faker_pool_precondition_met_seed` (JC-5) | deterministic REUSE with `seed.pool_size is None`. Read by the chunked native route (`faker_pool_precondition_met`, line 212), the native pool rejection (line 244), the sequential route (`execution/_sequential_native_ops.py:421`), out-of-core admission (`execution/out_of_core/_compat.py:388`) and the out-of-core payload (`execution/out_of_core/_faker_native.py:88`) |
| R2 | `execution/native/_faker_positional_admission.py:56-61` `positional_faker_failures` (stage A) | non-deterministic REUSE with no `pool_size` in the raw config. Read by the chunked veto, the `when:` gate, the static route decision, the evidence planner, the output-type pin and the unified slice (`execution/physical/_shadow_bindings.py:219` `positional_faker_bindable`) |
| R3 | `execution/_chunked.py:244-250` conditional failures | deterministic faker of any provider with no `pool_size` (`chunked_strategy_conditions_unmet`) |
| R4 | `execution/_chunked.py:496-500` pool pre-warm | raises `ValueError` when `col_seed.pool_size is None` (unreachable today because R3 refuses first) |
| R5 | `execution/physical/_shadow_bindings.py:328-330` and `execution/physical/_plan.py:77` | leaves the node unbound when `plan_slice.pool_size is None`; `PoolBinding.plan_pool_size` is typed `int` |

A second copy of the default: `generation/pool/_validate.py:134` writes the literal `10_000` in place of the shared constant.

## 2. Established solutions

Search run: how pooled or dictionary-based fake-data tools treat an omitted pool size (Faker providers, SDV and RDT `AnonymizedFaker`, Tonic "consistency" docs); how the engine's own oracle resolves it.

- RDT `AnonymizedFaker` and SDV draw from Faker directly and have no pool-size knob; Tonic consistency maps a source value to a fake over a fixed hash domain that the user does not declare. None of them asks the user to state a capacity to get the fast path. A default capacity applied the same way on every route is the common pattern.
- The engine already has the one resolver (`effective_pool_size` over `resolve_runtime_pool_size`, decision record `docs/archive/discussions/2026-07-13-de11-pool-size-precedence.md`). Every runtime pool builder already goes through it by way of `resolve_faker_pool_identity`: the oracle handler (`execution/_strategies/_faker.py:90`), the chunked native route (`execution/native/_chunk_masking.py:423`), the unified slice (`execution/physical/_shadow_batch_runner.py:305`), the chunked pre-warm (`execution/_chunked.py:506`) and out-of-core (`execution/out_of_core/_faker_pool.py:139`).
- So no new code computes a size. The fix deletes the refusals and lets each route pass the compiled `seed.pool_size` (which may be `None`) to `resolve_faker_pool_identity`, as the oracle does. The explicit declaration was required (capability-gaps WS4, `execution/_chunked.py:34-48`) because "every whole-run input is declared in config rather than derived from the data". The default is a constant, not derived from the data, so that reason does not cover it.

### Reuse inventory

- `effective_pool_size` (`generation/pool/_identity.py:27`) and `DEFAULT_POOL_SIZE` (`generation/pool/_runtime_pool_size.py:25`): the one default and the one resolver, reused as they are.
- `resolve_faker_pool_identity` (`generation/pool/_identity.py`): the shared oracle and native pool identity, already called on every route.
- The existing provider-output type checks (`faker_provider_output_not_string`, `chunked_faker_nondeterministic_pool_not_string`): reused for the custom-provider case.
- No new sizing code.

## 3. Guarantee and non-goals

After this slice:

1. On every route (unified slice, chunked native, chunked oracle leg, sequential, out-of-core), a `faker` column with `cardinality_mode` absent or `reuse` and no `pool_size` gets the same admission decision, the same pool identity and the same output values as the same column with `pool_size: 10000`. This holds for deterministic and non-deterministic columns.
2. Default `faker(person_first_name)` and `faker(person_last_name)`, deterministic with a namespace or not, run on the native route under 100,000 rows and on the chunked route at 100,000 rows or more, for every source type those routes take today with an explicit `pool_size`.
3. Non-null output values equal today's pandas output for the same config, row for row (F1).
4. One resolver: no admission check reads `pool_size`; runtime consumers pass `seed.pool_size` through to `resolve_faker_pool_identity`. `generation/pool/_validate.py:134` uses `effective_pool_size` in place of the literal.
5. `pool_size_location_conflict` at compile is unchanged.

Non-goals: new providers on the native allowlist (FAKER-NATIVE-WIDEN); `unique`, `match_source_cardinality` and `scale_source_cardinality` modes (they keep whole-run state and stay full frame); composite providers and their own `pool_size: int = 10_000` defaults in `generation/composite/` (logged as a follow-up); generation-side pools; the CLI route label (ROUTE-LABEL-TRUTH); `when:` rules for faker (unchanged: a closed-grammar predicate runs, an open one refuses).

## 4. Enumerations

### Exit paths

- Admitted: the column runs native or chunked and the pool comes from `resolve_faker_pool_identity` (`execution/native/_chunk_masking.py:423`, `execution/physical/_shadow_batch_runner.py:305`).
- Declined for a reason other than pool size (provider outside the allowlist, `unique` mode, open `when:`): unchanged coded decline, full frame.
- Custom provider returns non-strings: `faker_provider_output_not_string` before the first chunk (F5).
- `deterministic` with no namespace: the oracle's existing coded error (`execution/_strategies/_faker.py`).
- `pool_size_location_conflict` at compile (`plan/_pool_size.py`): unchanged.
- Out-of-core pool budget: each distinct pool reserves `pool_size * 4096` bytes (`execution/out_of_core/_faker_pool.py:56`, `:185`) against `min(run budget, 256 MiB)` (`execution/out_of_core/_runner.py:217-221`). A default column reserves about 40 MiB, so a job with several default columns of distinct pool identities could raise `out_of_core_faker_pool_budget_exceeded` mid-run, at the first table that needs the pool, where the column used to decline. This plan moves the check before the run (section 5, F6b): the runner sums the reservations of every distinct pool identity the plan admits, before the scratch arena opens and before any batch, and raises the same code there. The run then fails clean with no partial work. The pre-run sum applies to explicit `pool_size` columns too; the per-pool check at `:186` stays as the backstop.

### Routes

| Route | Today, no `pool_size` | After |
|---|---|---|
| Unified slice (single table, under 100k rows) | refused at R1 or R2, table on pandas | admitted under the same conditions as `pool_size: 10000` |
| Chunked native (100k rows or more, string source) | refused at R1, R2 or R3, table full frame | admitted |
| Chunked oracle leg (non-string source, or a deterministic provider outside the allowlist) | refused at R3 | admitted, the same as `pool_size: 10000` today |
| Sequential (FK jobs) | refused at R1 | admitted for allowlisted providers |
| Out-of-core | refused at R1 (`out_of_core_faker_pool_unsupported`) | admitted for allowlisted providers with an exact `string` source |
| Full-frame pandas | runs, builds 10,000 | unchanged |

### Column shapes

- deterministic, namespace, REUSE, allowlisted provider: native on every route above.
- deterministic, namespace, REUSE, provider outside the allowlist: chunked oracle leg at 100k rows or more (as with an explicit `pool_size` today); full frame below.
- non-deterministic REUSE, allowlisted provider: position-keyed native.
- non-deterministic REUSE, provider outside the allowlist: full frame (stage A still refuses on the provider).
- `deterministic` with no namespace: unchanged; the oracle raises its own coded error.
- `pool_size` written as an explicit `null` at top level or in `provider_config`: the same as absent.

### FK shapes

- Faker on an FK key column: never native (the chunked FK gate admits only `hash` as a self-masking key). Unchanged.
- Faker on a non-key column of a parent or child table: follows the sequential row (`execution/_sequential_native_ops.py:421`) and the out-of-core row (`execution/out_of_core/_compat.py:388`) above. F6 covers it.
- Single table, no FK edges: unified slice or chunked rows above.

### Fields

- `pool_size` at top level of the column entry: absent, `null` or an int. Absent and `null` now mean 10,000 on every route.
- `provider_config.pool_size`: same rules; a value here still wins over the default (`generation/pool/_runtime_pool_size.py:25` `resolve_runtime_pool_size`).
- `cardinality_mode`: absent or `reuse` is in scope; the other modes are not.
- `deterministic` and `namespace`: unchanged meaning.

### Output surfaces

- Masked column values: unchanged (F1).
- Type of an empty or all-null output column: becomes `string` on native and chunked routes (section 10, marked byte change).
- Route evidence: `rust_pool_select` in place of `pandas_oracle`.
- Refusal text: `chunked_strategy_conditions_unmet` (`execution/_chunked.py:244`) no longer names `pool_size`.

## 5. Slices and size

One slice.

| File | Change | Lines (estimate) |
|---|---|---|
| `execution/native/_requirements.py` (656) | drop the `pool_size` clause from `faker_pool_precondition_met_seed`; docstrings say the size resolves through `effective_pool_size` | -3, +3 |
| `execution/native/_faker_positional_admission.py` (143) | drop the `pool_size` failure from `positional_faker_failures`; module docstring | -6, +2 |
| `execution/_chunked.py` (589) | drop the `pool_size` failure (lines 244-250) and the pre-warm `ValueError` (lines 496-500); module docstring lines 38-56 | -14, +4 |
| `execution/physical/_plan.py` (238) | `PoolBinding.plan_pool_size: int \| None`, docstring | +2 |
| `execution/physical/_shadow_bindings.py` (441) | drop `pool_size is None` from the faker guard; docstring line 224 | -1, +1 |
| `execution/out_of_core/_compat.py` (586), `execution/out_of_core/_faker_native.py` (306), `execution/native/_chunked_schema_rule.py` | refusal message and docstrings stop naming an explicit `pool_size` | text only |
| `execution/out_of_core/_runner.py` (368), `execution/out_of_core/_faker_pool.py` (239) | `OocFakerPoolContext.check_plan_reservations(identities)`: sum distinct reservations, raise `out_of_core_faker_pool_budget_exceeded` before the arena opens; the runner calls it once after building the context | +20 |
| `generation/pool/_validate.py` (220) | `effective_pool_size(resolved_pool_size, {})` in place of the literal | 1 |
| `docs/compatibility-contract.md` | the non-deterministic REUSE paragraph (about line 997), the deterministic Faker paragraph, the ROUTE-OUTPUT-CONTRACT line for newly admitted columns | about 8 |
| `changelog.d/faker-default-pool.md` | `Breaking:` line plus `### Changed` | new fragment |
| Tests | new F1-F7 and the sentry; existing tests that pin the refusal flip (list below) | about 300 |

New public names: none. New reason codes: none. No file passes its size cap; `_requirements.py` is already over the 600-line aim and shrinks.

Existing tests that assert the old refusal and must flip to assert admission. This is the intended behavior change, so each flip keeps its file and test name and gets a new expectation; it is not a weakening:

- `tests/unit/execution/test_chunked.py::test_faker_without_pool_size_rejected`
- `tests/native/test_requirements_jc5.py::test_precondition_rejects_missing_pool_size`
- `tests/native/test_dispatch_faker.py`, case `missing_pool_size` (line 185) and the `LAST` column at line 350
- `tests/unit/execution/test_faker_positional_nondet.py`, `test_a_reuse_column_without_a_pool_size_keeps_the_veto_and_runs_full_frame`
- `tests/physical/test_unified_slice_faker.py`, case `missing_pool_size` (line 557)
- `tests/parity/test_phase_d_faker_seq.py::test_f5f_a_deterministic_faker_without_a_pool_size_declines` and the cases at lines 246 and 265
- any further hit of `grep -rn "pool_size=None\|without_pool_size\|missing_pool_size" tests/` that asserts a decline

The builder lists every flipped test in the report. Changed assertions in existing tests are a full-suite trigger (testing.md, "moved or deleted tests"), so this slice runs T3 on the merge head.

## 6. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `test_faker_default_pool.py` | `tests/parity/` | "Pipeline spine and routes": execution tests; cross-route equality tests live in `tests/parity/` | `test_phase_d_faker_seq.py` |
| `test_faker_pool_size_one_resolver.py` | `tests/sentry/defects/` | "Sentry test": recurring-defect class rules in `tests/sentry/defects/` | other defect sentries |
| `faker-default-pool.md` | `changelog.d/` | "Changelog fragments" | other fragments |

No new source module. `execution/` (cap 103) and `execution/native/` (cap 55) get no new file. The new sentry gets a row in `scripts/dev/sentry_registry.toml`.

## 7. Design notes

No new structure. One fact moves to one place: "how big is this column's pool" is answered only by `effective_pool_size`, reached through `resolve_faker_pool_identity`. Admission answers only "is this column's shape one the route can reproduce", and pool size is no longer part of that answer, because every size, the default included, reproduces.

Choke point: `resolve_faker_pool_identity` is already the only pool builder entry on every route. The guard is the sentry `test_faker_pool_size_one_resolver.py`, scoped to admission code so legitimate reads elsewhere (`measurement.pool_size` at `execution/native/_pool_quality.py:411`, `prepared.pool_size` at `execution/out_of_core/_faker_pool.py:185`, `INDEX_KAT.pool_size`) are out of its reach by construction:

- Modules walked (AST): `execution/native/_requirements.py`, `execution/native/_faker_positional_admission.py`, `execution/_chunked.py`, `execution/physical/_shadow_bindings.py`, `execution/out_of_core/_compat.py`, `execution/out_of_core/_faker_native.py`, `execution/_sequential_native_ops.py`.
- Rule: inside those modules, a `.pool_size` attribute or a `"pool_size"` key (`.get`, subscript) may not appear as an operand of a comparison (`is`, `is not`, `==`, `!=`), of `in` / `not in`, or as the test of an `if`, `while`, `and`, `or`, `not` or ternary. Passing the value on (an argument or a keyword value) is allowed, so `PoolBinding(provider, plan_pool_size=plan_slice.pool_size)` at `_shadow_bindings.py:328` passes without an allowlist entry.
- Named allowlist (module, function, reason): starts empty. A new entry needs a reason in the sentry file.
- Seeded cases in the sentry's own test: `seed.pool_size is None`, `if cfg.get("pool_size"):`, `"pool_size" in cfg`; each must fail. A seeded `f(x.pool_size)` must pass.
- The mutation that must turn it red: restore R2's `col_entry.get("pool_size") is None` clause.

F2 is the behavior proof beside it: each admission entry point decides the same for a column with no `pool_size` and for the same column with `pool_size: 10000`.

## 8. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | refusal and evidence text | wording changes only; no value or path added | existing value-free sentries | n/a |
| 2 | Cleanup missing on an exit path | out-of-core budget failure | the pre-run reservation sum raises before the scratch arena opens, so nothing needs cleanup | F6b | move the check after `ScratchArena.fresh` (F6b red on the leftover scratch check) |
| 3 | State and concurrency | the pool cache across chunks | the pre-warmed pool and every chunk use one identity from `resolve_faker_pool_identity` | F1 at 120k (several chunks) | resolve the pre-warm size from the literal 10,000 (F1 variant with `provider_config.pool_size: 500` red) |
| 4 | Route parity and silent fallback | five routes | one resolver; sentry plus F2 | F1, F2, F6, sentry | restore the R2 clause only (sentry and F2 red) |
| 5 | Referential integrity | none | N/A: faker is not an FK key on native routes | n/a | n/a |
| 6 | Untrusted producer | a custom provider registered under an allowlisted name whose pool holds non-strings | the existing `faker_provider_output_not_string` and `chunked_faker_nondeterministic_pool_not_string` checks run on the resolved pool | F5 | skip the pool type check (F5 red) |
| 7 | Check then use | none | N/A: admission reads only the compiled plan and the config, which do not change between the check and the run | n/a | n/a |
| 8 | Weak tests | value equality alone misses a type change | F1 compares Arrow tables with schema, and the output hash | F1 | compare `to_pylist()` only (reviewer checks F1's assertion form) |
| 9 | Refactor drift | configs that set `pool_size` | unchanged path; existing explicit-size tests pass unchanged | existing parity suites | n/a |
| 10 | Frozen contract drift | compatibility-contract faker paragraphs; empty or all-null column type | contract entry rewritten; Breaking line | F4, docs review | leave the old "explicit `pool_size`" wording (reviewer check) |

## 9. Acceptance tests (each fails before the change unless marked)

- **F1 output equality.** For each of `faker(person_first_name)`, `faker(person_last_name)`, `faker(person_first_name) in ns deterministic`: run 2,000 rows and 120,000 rows (string source) with no `pool_size`, with `pool_size: 10000`, and on the forced pandas full-frame route (auto-chunk off, native off). All three outputs are equal as Arrow tables (`equals`, schema included) and their output hashes are equal. Values already agree before the change, so the fail-before half is the route assertion: the no-`pool_size` run reports `rust_pool_select` at 2k and a chunked route with `rust_pool_select` per chunk at 120k. Before the change it reports `pandas_oracle` full frame. A variant with `provider_config.pool_size: 500` checks that a declared size still wins.
- **F2 equal admission.** Each admission entry point (R1 through `faker_pool_precondition_met` and `_seed`, R2, R3, `positional_faker_bindable`, `out_of_core._compat._faker_conditional_rejection`, `out_of_core._faker_native.decline_reason`, `_sequential_native_ops` faker admission) decides the same for the column shapes of section 4 with no `pool_size` and with `pool_size: 10000`. The entry points are this fixed list; the sentry covers a new admission site added to the walked modules. Fail-before: R1, R2 and R3 refuse the no-`pool_size` column.
- **F3 non-allowlisted deterministic providers.** `faker(person_email) in ns deterministic`, no `pool_size`, 120,000 rows: runs on the chunked oracle leg, output equal to the forced full-frame run. Then every provider the live registry classifies `pool_native` (`execution/native/_provider_class.classify_provider`), deterministic with a namespace and no `pool_size`, at a chunk size that forces three or more chunks: each output equals its full-frame output, or the job fails before the first chunk with an existing coded refusal. Fail-before: the job runs full frame. If a provider gives different output or `chunked_schema_mismatch`, the builder stops and reports: that is a defect of the explicit-`pool_size` path too, and the owner decides.
- **F4 degenerate type (marked byte change).** An empty table, and an all-null source column, with default `faker(person_first_name)`: the output column is Arrow `string` on the unified slice and chunked routes, as it already is with `pool_size: 10000`. Fail-before: pandas inferred `double` (empty) and `null` (all-null).
- **F5 custom provider.** A custom provider registered as `person_first_name` that returns integers, no `pool_size`: fails with `faker_provider_output_not_string` before any chunk is written. Fail-before: it ran full frame and succeeded. Named in the changelog as a new failure.
- **F6 sequential and out-of-core.** A two-table FK job whose child has default deterministic `faker(person_last_name) in ns` over a string column: the sequential route reports a native faker column, and the output equals the forced full-frame run; the out-of-core route admits the column with the same output. Fail-before: `faker_not_deterministic_reuse_variant` and `out_of_core_faker_pool_unsupported`.
- **F6b out-of-core budget.** An out-of-core job with a run budget of 100 MiB and three default faker columns with distinct pool identities (first name, last name, first name in a second namespace): the job fails with `out_of_core_faker_pool_budget_exceeded` before the arena opens and before any batch, the message names no source value, and no output or scratch file is left. The same job with two such columns runs. Fail-before: the columns declined with `out_of_core_faker_pool_unsupported`; with explicit `pool_size: 10000` the budget error came mid-run, when the third pool was prepared.
- **F7 explicit null.** `pool_size: null` at top level and in `provider_config` behaves as absent on every route (extends `tests/native/test_dispatch_faker.py::test_explicit_null_pool_size_falls_back_to_provider_config_or_default`). The pool half is an unchanged-behavior control; admission fails before.
- **S1 sentry.** `test_faker_pool_size_one_resolver.py` passes on the change and fails on each seeded case.

Mutations (record the head they ran on): restore the R2 clause (sentry and F2 red); restore the R1 clause (F2 and F6 red); drop the pre-run sum (F6b red); hard-code `plan_pool_size=10000` in `_shadow_bindings` (F1 `pool_size: 500` variant red).

Performance evidence (performance.md): the audit's 2k and 120k probe on the Dell node through `vm-run`, before and after, three runs each, wall time and peak RSS for default first name. Expected: the 120k case moves from full frame to chunked. The numbers go in the PR body.

## 10. Frozen contracts and compatibility

- Output values: unchanged (F1).
- **Byte change, marked:** a newly admitted default faker column whose output is empty or entirely null is typed Arrow `string` on the unified slice and chunked routes, where pandas inferred `double` (empty) or `null` (all-null) before. It is the ROUTE-OUTPUT-CONTRACT entry that already applies to `pool_size: 10000` (`docs/compatibility-contract.md`, about lines 1007 and 1032).
- Fragment first line: `Breaking: a faker column with no pool_size now runs on the native and chunked routes; an empty or all-null output column is typed string, and a custom provider registered as person_first_name or person_last_name must return strings; an out-of-core job whose faker pools pass the pool budget now fails before the run starts.`
- `chunked_strategy_conditions_unmet` no longer fires for a missing `pool_size`; the code stays registered for its other conditions.
- Plan serialization and digest: unchanged. `ColumnSeed.pool_size` stays `None` when the config omits it (`plan/_serialize.py:174`).
- `SEED_PROTOCOL_VERSION` is not touched.

## 11. Pre-mortem

- A pre-warm or chunk path still assumes `plan_pool_size` is an `int` and raises `TypeError` on `None`. F1 at 120k and F6 cover it; mypy flags it once `PoolBinding` is `int | None`.
- Out-of-core jobs with many default faker columns now hit the pool budget where the columns used to decline. F6b makes that a clean pre-run failure; the message tells the user to set a smaller `pool_size` or raise the budget.
- A non-allowlisted deterministic provider fails on the chunked oracle leg with `chunked_schema_mismatch` for a job that ran full frame before. F3 walks the registry to find this before merge; the stop rule is in F3.
- The pool-quality frozen tier (`execution/native/_pool_quality.py:111`) is calibrated at 10,000 and now sees more columns at the same size. No change.
- The CLI run card still says pandas for some chunked runs until ROUTE-LABEL-TRUTH lands. Not this row.

## 12. Open questions for the owner

None. The byte change and the earlier out-of-core budget failure in section 10 follow the owner direction of 2026-11-22 and is already the recorded behavior for an explicit `pool_size`.
