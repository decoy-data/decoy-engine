Status: plan (revision 2, 2026-11-22; Dennis R1 PASS-with-edits, items H1-H3, M and L closed in this revision)

# ROUTE-LABEL-TRUTH: the run card names the route that ran and the first column that declined (with a slim SEAM-REASONS)

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap rows: ROUTE-LABEL-TRUTH (new, V1, rank 3 in the V1 fast-path audit) and the V1 part of SEAM-REASONS (run group candidate, moved from 1.1 into V1 by the owner on 2026-11-22, with PER-COLUMN-ROUTING). Two slices: engine first, then the CLI with the engine pin bump.

Anchors: a path with no prefix is in this repository (decoy-engine) under `src/decoy_engine/`; `tests/` and `docs/` are repository paths; `CLI:` is the decoy CLI repo. Read at engine `origin/main` `70881ad79` (0.28.3) and CLI `origin/main` `79099f04` (pins `decoy-engine==0.28.3`). Line numbers are at those heads.

Sources: vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md` ("Other routing facts", "What cannot reach a fast path in V1"); CLI `docs/roadmap/groups/run.md` (SEAM-REASONS candidate text); CLI `docs/handoffs/2026-11-19-engine-physical-seam.md` step 1 only; CLI `docs/records/2026-11-15-proportionality-audit/REMEDIATION.md` items A5, A6, J3; `docs/records/2026-11-19-engine-speed-and-route-completeness.md` section 10 class 4.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN, Proportion), `risk-and-exceptions.md`, `feature-dev.md`, `refactoring.md`, `api-and-compatibility.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (Test depth), `catalogs/recurring-defects.md`, `architecture.md`, `cross-cutting-concerns.md`, `security.md` (value-free evidence), `observability-and-resilience.md`, `documentation.md`, `workspace-and-vcs.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where Things Go"); CLI `CODEMAP.md`.

Risk: R2. It adds members to a public result type (`RouteSummary`), adds one public function, adds evidence keys to `quality_metrics`, changes run-card and `decoy run --json` text, and turns one silent reroute into a coded failure (A5). Output data bytes do not change. Plan review: Dennis, then Codex. Code gate: Codex and Dennis (`/code-review high`: masking lane).

Owner direction applied (2026-11-22): V1 must be fast and reproducible, and pre-V1 byte changes are allowed. This plan changes no output data. Its evidence and text changes are marked in section 10 and in the changelog `Breaking:` lines.

## 1. Frame

Three user-visible problems, all from one cause: the lanes do not say why they declined, so the CLI guesses.

1. **Wrong label.** At 120k rows a table of `passthrough`, `redact`, `truncate` or `text_redact` columns runs every column as `arrow_python` on the chunked lane, but the run card says `pandas (streamed lane)`. `CLI:src/decoy/_native_gate.py:425-436` (`classify_route`) labels any auto-chunk run with no compiled call as pandas. `route_summary` exposes only `native_executed` (`execution/pipeline/_route_summary.py:60`), not the per-column executed backend that both lanes already record.
2. **Silent decline.** `cheap_admission` (`execution/_unified_slice_admission.py:196`) and `resident_contract_admission` (`:410`) return `None` at about 40 sites. The table then runs on the pandas oracle and nothing records why (docstring at `:212-216`: "the coded reason is a nice-to-have"). The chunked lane already records coded per-column declines (`native/_route_decline_codes.py`, OBS-2b, `quality_metrics["chunked_route"]["decline_records"]`), but `route_summary` never reads them.
3. **A copy of the rules in the CLI.** `CLI:src/decoy/_native_gate.py:200-291` (`static_native_eligibility`, audit J3) and `_NATIVE_STRATEGIES` (`:71`) mirror the engine's admission. They are already stale: `faker`, `date_shift` and `fpe` are native operators in `execution/_operator_registry.py`, but not in the CLI set.

Two audit defects sit in the same code:

- **A5.** `execution/_unified_slice.py:361`: `except Exception` logs a class name and reruns the table on pandas. A real defect in the default-on lane becomes a slower run with no evidence.
- **A6.** `execution/physical/_compiler.py:444`: `except Exception: return None` around `post_scan_resident_for`.

Kernel-less families (owner, 2026-11-22: named exceptions in V1): `shuffle`, `geo_generalize`, `formula` and the derived kinds, `nested`, `joint_mask`, `tokenize`, and non-poolable Faker providers. Today they decline under generic codes (`fallback_policy_not_native`, `no_native_kernel_or_pool`) or under no code at all.

## 2. Established solutions

Search run: how query engines report why a fast path was not taken (Spark, Gluten/Velox, Polars, DataFusion, DuckDB); how error registries carry a stable code with a fixed message (RFC 9457, gRPC status). In-codebase: OBS-2b decline records, the F29 reason registry, F06 `declared_casting/_refusals.py`.

- **Fallback reasons per operator: Apache Gluten.** Gluten's validation marks each Spark plan node that cannot offload with a fallback reason and reports them (`spark.gluten.sql.fallbackReport`, the `GlutenPlanFallbackEvent` with `fallbackNodeToReason`). The reason is attached at the node that declined, and the summary shows the node and the reason. This plan follows that: the decline is attached to the column (node) that caused it and carries a registered code.
- **Polars** marks nodes its streaming engine cannot run and falls back for them; **DuckDB** and **DataFusion** report the physical operator chosen per node in `EXPLAIN`. All of them show the executed operator, not the requested one. The label in this plan reads the executed backend per column.
- **Stable code plus fixed summary: RFC 9457** (problem type separate from occurrence detail). The engine's F29 registry (`reasons/`) already does this; codes go there, not into a second taxonomy.
- **In-codebase reuse:** `native/_route_decline_codes.RouteDeclineRecord` (code, table, column, table_wide) is the record shape; `reasons.route` already holds most of the needed codes (`FK_RELATIONSHIP`, `VALIDATORS_PRESENT`, `VAULT_WRITER_REQUESTED`, `WHEN_*`, `FAKER_PROVIDER_NOT_NATIVE`, `FPE_CHECKSUM_NOT_NATIVE`, `*_EXT_UNAVAILABLE`, `UNCOVERED_OR_MISSING_COLUMNS`, `NON_SCALAR_NODE`, `GROUP_KEY_SIBLING_*`); `native/_provider_class.classify_provider` already says whether a Faker provider is poolable.

No custom mechanism is needed: the plan threads an existing record type out of two functions that return `None` today, and adds codes to the existing registry.

### Reuse inventory

- `native/_route_decline_codes.py:24` `RouteDeclineCode`, `:61` `RouteDeclineRecord`, `column_decline`, `table_decline`: the record and the closed vocabulary.
- `reasons/route/`: the catalog package (`_part1.py` 303 lines, `_added.py`, `_f06.py`, `_sink.py`).
- `native/_chunked_evidence.py:116` `executed_backend`: the one executed-backend rule, already shared by both lanes; `_unified_slice_evidence.assemble_node_evidence` already writes `executed_backend` per node.
- `execution/pipeline/_route_summary.py`: the one reader of route evidence, public through `decoy_engine.route_summary`.
- `native/_provider_class.classify_provider`: poolable or not.

## 3. Guarantee and non-goals

After this plan:

1. Every decline of the unified slice, in either stage, returns a `RouteDeclineRecord` with a code registered in `reasons.route`. No stage returns `None`. Two cases are "not offered", not declines, and record nothing: the flag is off (`unified_slice_enabled=False`), and the routed lane is not full-frame (the chunked or FK route ran and records its own evidence).
2. A column-attributable decline names the column. The recorded decline is the first check that fails, in the order admission runs its checks today. That order is not "all table-wide checks first": `cheap_admission` interleaves config checks with column checks (the `vault: true` and `when:` column checks sit between table checks), and `resident_contract_admission` runs table checks (`_unified_slice_admission.py:460-465`, empty or duplicate nodes) and then the per-node loop (`:467`). This plan keeps that order unchanged and records it; it only makes the per-node loop visit nodes in canonical work order (`_runner.in_work_order`), so the column chosen is deterministic.
3. **Why a node has no binding (one source).** Today `binding is None` (`_unified_slice_admission.py:470`) carries no reason, and `PhysicalNode` (`physical/_plan.py:176-192`) has no field for one. The reason already exists where `fallback_policy` is decided: `requirements_for` (`native/_requirements.py`) calls `native_kernel_rejection` (`:180`) and `native_pool_rejection` (`:230`). This plan adds `rejection: RouteDeclineCode | None` to `NodeRequirements` (`native/_requirements.py:250-263`), set by `requirements_for` from those same two calls through `column_decline_code`, and adds `decline_code: str | None` to `PhysicalNode`. `_build_nodes` (`physical/_compiler.py:305-360`) copies it. When `execution_binding_for_slice_node` (`physical/_shadow_bindings.py:256-290`) returns `None` for its own reasons (strategy outside `SLICE_STRATEGIES`, `output_arrow_schema is None`), `_build_nodes` sets `slice_strategy_not_bound` or `slice_output_type_indeterminate`. Admission reads `node.decline_code`; it never recomputes a reason. Plain random `categorical` (`categorical_not_deterministic`) and `hash` with a rejected config are covered in E2.
4. The decline code for a column whose strategy has no native operator comes from one function, `column_decline_code`, used by `requirements_for` (so by the unified slice and the chunked lane). Kernel-less families get these new registered codes:
   - `kernel_less_whole_column`: `shuffle`, `geo_generalize`.
   - `kernel_less_expression`: `formula`, `derived`, `derived_aggregate`, `grouped_series`.
   - `kernel_less_multi_column`: `nested`, `joint_mask`.
   - `kernel_less_vault`: `tokenize`.
   - `kernel_less_per_row_faker`: a Faker provider that `classify_provider` marks not poolable, and composite bundles.
   - `no_native_operator`: any other strategy with no native operator (for example `bucketize`, `top_code`, `code_set`, `windowed_date`). These are candidates for later rows, not named exceptions.
   A poolable Faker provider outside the allowlist keeps `faker_provider_not_native`; `fpe` with `checksum` keeps `fpe_checksum_not_native`.
   The family map is not a third free list. `KERNEL_LESS_FAMILY` maps strategy to a `RouteDeclineCode` member (not a string), and a sentry checks it against the two lists that already describe these strategies: every strategy whose capability row in `native/_capabilities.py` has `is_global=True` (`:104`, `:131`) must map to `KERNEL_LESS_WHOLE_COLUMN` or `KERNEL_LESS_EXPRESSION`, and no strategy in `CHUNK_SAFE_STRATEGIES` (`execution/_chunked_fk_vocab.py:44`) may map to `KERNEL_LESS_WHOLE_COLUMN`. A disagreement fails the sentry.
5. `quality_metrics["unified_slice_decline"]` holds `{code, table, column, table_wide, strategy}` when the slice was offered and declined. `strategy` is the configured strategy name of `column`, or `null` for a table-wide decline. No value, expression, provider argument, type text or exception text.
6. `RouteSummary` gains two members:
   - `declines: tuple[RouteDecline, ...]`: per routed table, its first decline, from the unified-slice block or from the first `chunked_route.decline_records` entry. `RouteDecline` holds `table`, `column`, `strategy`, `code` and `summary` (the registry's fixed summary).
   - `executed_backends: tuple[str, ...]`: the sorted distinct `executed_backend` values over every lane column (unified-slice nodes and chunked columns), empty when no lane evidence exists.
7. A new public function `native_config_outlook(config) -> NativeConfigOutlook` answers, from config alone:
   - `decline`: a registered code or `None`, whether the job can be offered the unified slice. This is the config half of `cheap_admission`, moved out so `cheap_admission` calls it: one function, two callers.
   - `needs_companion`: computed per node, not per strategy name. The outlook compiles the plan from config (`compile_native_plan` with an empty profile, as `_static_route_decision` does at `native/_dispatch.py:264-271`) and calls `requirements_for` on each mask node. `needs_companion` is true only when some node has `fallback_policy == "native"` and its operator has a `required_kernel` in `OPERATORS`. So a plain random `categorical` column (rejected `categorical_not_deterministic` by the compiler) does not need the companion, and a broken companion does not fail closed on that job. This keeps the behavior `CLI:tests/unit/test_native_gate.py:234-244` pins today.
8. A5 (`execution/_unified_slice.py:358-360`, the `except Exception` that logs `_REROUTE_LOG` at `:74` and returns `None`):
   - A `DecoyError` subclass (`ExecutionError`, `ConfigError`, `RowErrorsFailedError` and the others) and `MemoryError` pass through unchanged: same class, same code, same exit as on the oracle. Today they are swallowed and the oracle reruns the table, which then raises the same typed error a second time or, worse, succeeds differently.
   - Only a foreign exception (not a `DecoyError`, not `MemoryError`) is wrapped. It raises `UnifiedSliceInvariantError` with code `unified_slice_unexpected_error`, raised after the `except` block closes (recurring defect 3: no `__context__`). The message holds the exception class name, the table name and the rollback hint `rerun with --no-native to bypass the native lane`. Never the exception text.
   - The code is registered in `reasons/runtime/_part3.py` next to `UNIFIED_SLICE_INVARIANT_VIOLATION` (`:262`), under the same `_catalog.runtime("UnifiedSliceInvariantError")` declarer. The class keeps its class-level `code = reasons.runtime.UNIFIED_SLICE_INVARIANT_VIOLATION` (`_unified_slice.py:93`); the A5 raise passes `code=reasons.runtime.UNIFIED_SLICE_UNEXPECTED_ERROR` to the `DecoyError` constructor, which sets the instance `.code` (the same way the coded `ShadowDifference` path sets its code today).
   - Merge condition for slice 1: on the release candidate, count `unified_slice_unexpected_exception_reroute` log lines over the T3 full suite and over the prod-sim corpus (on today's main, before the change). The count must be zero. A non-zero count names a real lane defect to fix first, because after this change it fails the run.
9. A6: `_post_scan_resident` catches only the named error `post_scan_resident_for` raises for a malformed post-scan block (the builder names the class at DEVELOP from `_transforms_gate.py:80` and the config readers it calls); anything else propagates.
10. CLI: the route label reads `executed_backends`; the run card and `--json` show the first decline; `static_native_eligibility`, `_NATIVE_STRATEGIES`, `_COMPANION_DEPENDENT_STRATEGIES` and `_has_when_gate` are deleted and `native_config_outlook` replaces them. `decoy explain native` (`CLI:src/decoy/cli/explain.py:305-341`) is rewritten to the new label words.
11. Output data is unchanged byte for byte on every route.

Non-goals: SEAM-EXPLAIN (a physical plan for every job); the audit's C4, C5 and E3 items; per-column routing (separate plan, `2026-11-22-per-column-routing.md`, which builds on this one); a decline list with every column (only the first per table; the full list is SEAM-EXPLAIN); changing any admit or decline outcome, except A5; reason codes for the FK, sequential and out-of-core routes (they already record `route_reason`); the companion install message (NATIVE-MISSING-WARN).

## 4. Enumerations

### Exit paths

- A5, foreign exception: `UnifiedSliceInvariantError(code=unified_slice_unexpected_error)`, a runtime failure (exit 3 on the CLI, as for the other invariant errors). Today this case reruns on pandas.
- A5, `DecoyError` subclass or `MemoryError`: raised unchanged, with its own code and exit. Today it is swallowed and the oracle reruns.
- Every other exit is unchanged. A decline still runs the table on the pandas oracle, which fails or succeeds as today.

### Routes

- Unified slice offered and admitted: no decline; node evidence as today.
- Unified slice offered and declined in `cheap_admission`: decline recorded; oracle runs.
- Declined in `resident_contract_admission` or by the `inputs.caller_sources` identity check (`_unified_slice.py:214`): decline recorded; oracle runs. The identity miss gets code `slice_source_identity_changed`.
- Declined because `declared_route_guard` refused (`_unified_slice.py:391`): today noted under `execution.declared_route_refusals`; this plan also records the same registered code as the slice decline, so `route_summary` reads one source.
- Chunked lane (auto-chunk, single table and multi-table split, and the mixed route's mask tables): `declines` reads `decline_records`; `_route_summary._units` already walks all three shapes.
- `--chunked` CLI runs (no `ExecutionResult`): label unchanged (`pandas chunked stream`).

### FK shapes

N/A: an FK job never reaches either lane; `fk_relationship` is already the chunked lane's table-wide code, and the unified slice records it the same way when `profile.relationships` is set.

### Fields

- `quality_metrics["unified_slice_decline"]` (new key).
- `RouteSummary.declines`, `RouteSummary.executed_backends` (new members), `RouteDecline` (new type, exported beside `RouteSummary`).
- `NativeConfigOutlook` (new type) and `native_config_outlook` (new function).
- CLI `decoy run --json` `native_route.decline` (new optional member) and the label strings.

### Output surfaces

- `quality_metrics["unified_slice_decline"]`, written by `execution/_pipeline_full_frame.py:171-177`.
- `RouteSummary`, built in `execution/pipeline/_route_summary.py:60`.
- The CLI run card fact `Route` at `CLI:src/decoy/cli/run/_render.py:177`, and `decoy run --json` `native_route`.
- `decoy validate` preflight line `native.eligibility` at `CLI:src/decoy/cli/preflight.py:561`.
- Output data: none (unchanged).

## 5. Slices and size

### Slice 1: engine (one PR)

| File | Lines now | Change | Expected after |
|---|---|---|---|
| `reasons/route/_slice.py` (new) | 0 | about 26 codes: the 5 family codes and `no_native_operator`, the cheap-stage codes with no existing equal, `slice_resident_type_not_admitted`, `slice_namespace_not_utf8`, `slice_operator_obligation_not_routed`, `slice_source_identity_changed`, `slice_strategy_not_bound`, `slice_output_type_indeterminate`, `faker_provider_output_not_string` | about 140 |
| `reasons/runtime/_part3.py` | n/a | `UNIFIED_SLICE_UNEXPECTED_ERROR` beside `UNIFIED_SLICE_INVARIANT_VIOLATION` (`:262`) | +3 |
| `native/_requirements.py` | 677 ceiling | `NodeRequirements.rejection`, set from the existing rejection calls | at most 677 (net about +6; the builder trims a docstring if needed, the ceiling is not raised) |
| `physical/_plan.py`, `physical/_compiler.py` | n/a, 446 | `PhysicalNode.decline_code`; `_build_nodes` copies it | +4, +8 |
| `reasons/route/__init__.py` | 9 | one star import | 10 |
| `native/_route_decline_codes.py` | 124 | new enum members; `column_decline_code(strategy, *, provider_class)` | about 175 |
| `native/_route_decline_codes.py` (holds `KERNEL_LESS_FAMILY`) | see above | `KERNEL_LESS_FAMILY: Mapping[str, RouteDeclineCode]` lives beside the enum it uses, so the operator registry stays a stdlib-and-pyarrow leaf | included above |
| `execution/_unified_slice_admission.py` | 559 | each `return None` becomes a coded record; config half moves out; column loop in work order | about 540 |
| `execution/pipeline/_native_outlook.py` (new) | 0 | `NativeConfigOutlook`, `native_config_outlook`, the config-only checks moved from `cheap_admission` | about 120 |
| `execution/_unified_slice.py` | 463 | returns `ExecutionResult | SliceDeclined`; A5 carve-out; the non-string pool reroute (`:247-256`) records `faker_provider_output_not_string` | about 490 |
| `execution/_unified_slice_when.py` | 98 | `when_columns_admitted` returns the first record or `None` | about 105 |
| `execution/_pipeline_full_frame.py` | 333 | stamps `unified_slice_decline` on the oracle result | about 345 |
| `execution/native/_dispatch.py` | 679 (ceiling 688) | two decline sites call `column_decline_code` (net about +2) | at most 688 |
| `execution/pipeline/_route_summary.py` | 220 | `RouteDecline`, `declines`, `executed_backends` | about 290 |
| `execution/pipeline/__init__.py`, root `__init__.py` | 39, n/a | export `RouteDecline`, `NativeConfigOutlook`, `native_config_outlook` | +6 |
| `execution/physical/_compiler.py` | 446 | A6 | 446 |

New public names: `RouteDecline`, `NativeConfigOutlook`, `native_config_outlook`. New evidence key: `unified_slice_decline`. Also: tests, a changelog fragment, a `docs/compatibility-contract.md` entry, a `docs/execution-backends.md` section "Why a table did not take the native lane" listing the family codes, the `docs/qa/` checklist rows for the new codes (the QA sentry reads reason codes), the public census and signature snapshots (`tests/sentry/release/`), and the module-size census if a pin moves (it may only move down).

Size target: about 520 source lines changed, about 650 test lines.

### Slice 2: CLI (one PR, after the engine release that holds slice 1)

| File | Lines now | Change |
|---|---|---|
| `CLI:src/decoy/_native_gate.py` | 492 | delete `static_native_eligibility` (92 lines), `_NATIVE_STRATEGIES`, `_COMPANION_DEPENDENT_STRATEGIES`, `_NATIVE_SOURCE_FORMATS`, `_has_when_gate`; `pre_execution_gate` scopes on `native_config_outlook`; `classify_route` reads `executed_backends`; `RouteClassification` gains `decline` (about 380 after) |
| `CLI:src/decoy/cli/preflight.py` | 839 | the `native.eligibility` line reads the outlook and names its code |
| `CLI:src/decoy/cli/run/_render.py` | 239 | one card fact `Declined`; `native_route.decline` in JSON (about 255 after) |
| `CLI:src/decoy/cli/explain.py` | n/a | `explain native` topic (`:305-341`): the route list uses the new label words, adds the mixed row and the `Declined:` line | 
| `CLI:tests/unit/test_native_gate.py` | n/a | the `static_native_eligibility` cases (`:76-343`) are rewritten against `native_config_outlook` (same configs, same expected verdicts; `:234-244` random categorical keeps `needs_companion is False`); the `_NATIVE_STRATEGIES` mutation test (`:121-135`) is deleted (the set is gone; the engine sentry replaces it) |
| `CLI:tests/e2e/test_source_format_dispatch.py` | n/a | `:416-431` rewritten to `native_config_outlook(...).decline` (format accepted gives `None`; `xlsx` and a missing format give the engine code) |
| `CLI:tests/unit/test_release_smoke_workflow.py` | n/a | `:259-261` compares the smoke config's strategies to the engine `OPERATORS` keys instead of `_NATIVE_STRATEGIES` |
| `CLI:tests/e2e/test_preflight_native.py`, `CLI:tests/e2e/test_run_native.py:322` | n/a | docstring references updated; assertions unchanged |
| `CLI:pyproject.toml`, lock, engine repin checklist files | | pin to the engine release |

Label rule (one function, `classify_route`), from `RouteSummary.executed_backends`:

| Executed backends | Label | `state` |
|---|---|---|
| contains `rust_companion` or `rust_pool_select`, and no Python backend | `native (compiled kernel)` | `native` |
| only `arrow_python` | `native lane (Arrow, no compiled kernel)` | `unified_slice` |
| only `pandas_oracle` | `pandas (streamed lane)` on auto-chunk, `pandas (legacy adapter)` otherwise | `pandas` |
| a compiled or Arrow backend and a Python one (`pandas_oracle` or `python_pandas`) | `mixed (native and Python columns)` | `native` when a compiled backend ran, else `unified_slice` |
| no lane evidence | `pandas (legacy adapter)` | `pandas` |
| any other value (`python_scalar`, `inherited`, or a backend added later) | `mixed (native and Python columns)` when a native backend is also present, else `pandas (legacy adapter)`; unknown names are treated as Python | as the matching row |

The mixed row cannot occur until PER-COLUMN-ROUTING lands. It is in the rule now so the CLI does not need a second change. `post_run_verify` is unchanged: `--native` still needs `state == "native"`.

Card line, when `declines` is non-empty: `Declined: <table>.<column> (<strategy>): <summary> [<code>]`, or `Declined: <table>: <summary> [<code>]` for a table-wide decline, plus `(+N more tables)` when several tables declined. JSON: `native_route.decline = {table, column, strategy, code, summary}` for the first one.

Size target: about 130 source lines removed net, about 250 test lines.

## 6. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `_slice.py` | `src/decoy_engine/reasons/route/` | "Reason codes": one catalog package per namespace | `_f06.py`, `_sink.py` |
| `_native_outlook.py` | `src/decoy_engine/execution/pipeline/` | "Pipeline spine and routes": new route modules go in `execution/pipeline/` (`execution/` is frozen at 103 direct modules; `pipeline/` has 16) | `_route_summary.py`, `_native_notice.py` |
| `test_slice_declines.py` | `tests/unit/execution/pipeline/` | engine execution tests, existing subpackage (flat `tests/unit/execution/` already has 275 entries) | `test_native_fallback_notice.py` |
| `test_route_summary_declines.py` | `tests/unit/execution/pipeline/` | same | same |
| `test_kernel_less_families.py` | `tests/sentry/defects/` | "Sentry test": recurring-defect class rules | existing choke-point sentries |
| `test_route_label_truth.py` | `CLI:tests/unit/` | CLI unit tests | `test_native_gate.py` |

`_native_outlook.py` must be added to `GUARDED_MODULES` in `tests/sentry/test_physical_seam_disconnection.py` (routing code, no `execution.physical` import), as `_route_summary.py` is. No package passes its fan-out cap: `reasons/route/` and `execution/pipeline/` both have room.

## 7. Design notes

- Principles: one place per fact. The family map lives once beside `RouteDeclineCode`, cross-checked against the capability table; the code choice for a column lives once in `column_decline_code`; the config-only admission rules live once in `native_config_outlook`, called by `cheap_admission` and by the CLI. Each removes a real copy: J3 is a copy today, and the chunked lane and the slice would otherwise grow two family tables.
- Pattern: Gluten fallback reasons per plan node (section 2).
- Typed results over `None`: each admission stage returns `T | RouteDeclineRecord`. No flag argument.
- Choke point: `RouteDeclineRecord.code` is a `RouteDeclineCode` member, and every member's value is a registered `reasons.route` code. The guard is the existing reason-registry sentry plus a new test that every `RouteDeclineCode` value is registered. Mutation: add a member with an unregistered string (guard red).
- Coverage guard for families: `tests/sentry/defects/test_kernel_less_families.py` asserts every mask strategy in `execution._strategies.SCALAR_HANDLERS` (and the composite strategies) is a key of `OPERATORS`, a key of `KERNEL_LESS_FAMILY`, or in the test's explicit `NO_NATIVE_OPERATOR` set, and checks `KERNEL_LESS_FAMILY` against `is_global` and `CHUNK_SAFE_STRATEGIES` (guarantee 4). A new strategy cannot ship without a decline name. Mutation: drop `shuffle` from `KERNEL_LESS_FAMILY` (guard red).

## 8. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | decline block, `RouteDecline`, card line, JSON | record holds code and schema identifiers only; `summary` comes from the registry; no exception text (A5 message has class name and table only) | E8 | put the exception message in the A5 error (E8 red) |
| 2 | Cleanup missing on an exit path | A5 raise | the lane writes nothing before the coordinator returns; publication is owned by the caller | E6 | n/a |
| 3 | State and concurrency | none | N/A: pure functions, no shared state, no context var | n/a | n/a |
| 4 | Route parity and silent fallback | both lanes, A5, A6 | every decline returns a registered record; A5 no longer reruns | E1, E2, E6 | restore `except Exception: return None` (E6 red); wrap `DecoyError` too (E6(b) red); return a decline without a code (E1 red) |
| 5 | Referential integrity | none | N/A: no keys touched | n/a | n/a |
| 6 | Untrusted producer | `quality_metrics` read by `route_summary` | `route_summary` skips malformed entries (existing `_block`, `_text_or_none`) | E4(d) | read `code` without a type check (E4 red) |
| 7 | Check then use | slice identity check | unchanged identity check, now coded | E2 | n/a |
| 8 | Weak tests | label tests that only check `state` | assert the label string and the executed backends | C1 | label from `native_executed` again (C1 red) |
| 9 | Refactor drift | config half moved to `native_config_outlook`; reasons moved to `NodeRequirements` | `cheap_admission` calls the outlook; admission reads `node.decline_code` | E9, E2 spy | inline a changed copy in `cheap_admission` (E9 red); recompute the reason in admission (E2 spy red) |
| 10 | Frozen contract drift | `RouteSummary`, `--json` `native_route`, card | additive members; compatibility contract and frozen-shape snapshot updated | E10, C6 | rename `declines` (census sentry red) |

## 9. Acceptance tests

Each fails before the change unless marked control.

Engine (slice 1):

- **E1 cheap-stage codes.** Parametrized over one-table configs, each with one decline cause: validators, quarantine, a post-scan model, fidelity report, post-validation, a vault writer, a `vault: true` column, table `transforms`, a non-file source, an extra resident table, an undeclared source column, a duplicate field name, a `LazySource`, a `when:` the chunked verdict refuses, a malformed Arrow table. Each returns a record with the expected registered code and `table_wide=True`, except the `vault: true` column and the `when:` column, which name their column. Fail-before: `None`.
- **E2 resident-stage codes.** 2,000-row tables, one declining column each, the rest `hash in ns`: `faker(person_email)` gives `faker_provider_not_native`; `faker(address_full)` gives `kernel_less_per_row_faker`; `shuffle` gives `kernel_less_whole_column`; `formula` gives `kernel_less_expression`; `fpe(..., checksum: npi)` gives `fpe_checksum_not_native`; `bucketize` gives `no_native_operator`; a float64 `hash` column gives `slice_resident_type_not_admitted`; a plain random `categorical` (no `deterministic`) gives `categorical_not_deterministic`; a `hash` column with a config the compiler rejects (for example a non-UTF-8 namespace) gives its compiler code, read from `PhysicalNode.decline_code`. A spy proves admission does not call `native_kernel_rejection` itself. Each names the column and strategy in `quality_metrics["unified_slice_decline"]`. Fail-before: no key.
- **E3 first column.** Columns `b: shuffle` and `a: faker(address_full)` (both decline): the record names the first in work order. Run twice with the column list reversed in config: same record.
- **E4 route summary.** (a) The E2 runs give `declines == (RouteDecline(table, column, strategy, code, summary),)` with `summary` equal to the registry summary for `code`. (b) A 120,000-row CSV with `faker(person_email)` on the chunked lane gives the decline from `decline_records`, with the strategy read from `chunked_route.columns`. (c) A multi-table split with two declining tables gives two entries, in table order. (d) Malformed `decline_records` entries (missing `code`, non-string `column`) are skipped, not raised.
- **E5 executed backends.** 120,000 rows: passthrough, `redact`, `truncate` gives `("arrow_python",)`; plus a `hash in ns` column gives `("arrow_python", "rust_companion")`; a `faker(person_email)` column alone (chunked oracle) gives `("pandas_oracle",)`; a `faker(person_email)` plus `shuffle` table runs full frame (shuffle does not chunk), the slice declines, and no lane evidence exists, so the result is `()`. 2,000 rows admitted: from the node evidence. Fail-before: no member.
- **E6 A5.** (a) A coordinator stub raising `KeyError` on an admitted table: the run raises `UnifiedSliceInvariantError` with code `unified_slice_unexpected_error`, the message names `--no-native`; the oracle is not called (spy); `__cause__ is None and __context__ is None`. Fail-before: the run succeeds on pandas. (b) Stubs raising `ExecutionError(code=X)`, `ConfigError`, `RowErrorsFailedError` and `MemoryError`: each propagates as the same object with its own code; the oracle is not called. Fail-before: swallowed and rerun. (c) `faker_provider_output_not_string`: a rebound provider that yields ints records that code in `unified_slice_decline` and the oracle runs, as today.
- **E7 A6.** A malformed post-scan block gives `None` as today; a stub raising `RuntimeError` inside `post_scan_resident_for` propagates. Fail-before: `None`.
- **E8 value-free.** For every E1 and E2 case, the decline block's keys are exactly `{code, table, column, table_wide, strategy}`, and no seeded sentinel cell value appears in `json.dumps(quality_metrics)`. The A5 error message holds no source value.
- **E9 one config half.** For the E1 corpus, `native_config_outlook(cfg).decline` equals the code `cheap_admission` records when the config check is the cause; `cheap_admission` calls `native_config_outlook` (spy). `needs_companion` is true when any column's strategy has a `required_kernel` in `OPERATORS`.
- **E10 kernel-less sentry.** `tests/sentry/defects/test_kernel_less_families.py` passes: every strategy is in `OPERATORS`, `KERNEL_LESS_FAMILY` or the explicit `NO_NATIVE_OPERATOR` set; every `is_global` capability maps to a whole-column or expression family; no `CHUNK_SAFE_STRATEGIES` member maps to `KERNEL_LESS_WHOLE_COLUMN`. Mutations: drop `shuffle` from the map (red); map `hash` to `KERNEL_LESS_WHOLE_COLUMN` (red).
- **E11 control: output unchanged.** The existing unified-slice parity suite (`tests/physical/`, the flag-on and flag-off gate) and the auto-chunk output-contract tests pass unchanged, before and after.

CLI (slice 2, against the engine release with slice 1):

- **C1 label.** `decoy run` on a 120,000-row CSV with `id` passthrough, `name: redact`, `note: truncate`: the card says `Route: native lane (Arrow, no compiled kernel)`, `--json` `native_route.state == "unified_slice"`. Fail-before: `pandas (streamed lane)`.
- **C2 decline shown.** 2,000 rows with `email: faker(person_email)` and `id: hash in ns`: the card has `Declined: people.email (faker): <registered summary> [faker_provider_not_native]`; `--json` has `native_route.decline` with those five members.
- **C3 named exception.** Same with `email: shuffle`: code `kernel_less_whole_column` and its summary.
- **C4 J3 gone.** `static_native_eligibility` and the three strategy sets no longer exist (import test). The existing `test_native_gate.py` and `tests/e2e/test_preflight_native.py` cases keep their outcomes: a broken companion still fails closed for a native-candidate config and does not block an FK, transform, quarantine, passthrough-only or plain random `categorical` job (`CLI:tests/unit/test_native_gate.py:234-244`, now through `needs_companion`); `--native --vault` still refuses. Every rewritten or deleted CLI test is listed in the slice 2 table.
- **C7 explain.** `decoy explain native` prints the five label rows of the label rule and no longer prints `unified slice (no compiled kernel)`. Fail-before: old words.
- **C5 control: `--native` evidence.** `--native` on the C1 table refuses with `native_require_no_evidence` (no compiled kernel ran); on a `hash` table it passes. Passes before and after.
- **C6 frozen shape.** The `run` frozen-shape snapshot gains the optional `native_route.decline`; regenerated with `python -m tests.e2e.release_freeze.write_shapes`, diff reviewed.

Test scope (both slices): T0 per edit; T1 impact selection plus the named tests and guard tests; T3 full suite at the merge head because each slice touches a frozen contract surface (`RouteSummary`, `--json`), with the failing-id diff against the saved main baseline. Mutations: the class-table mutations on `column_decline_code`, the admission decline returns and the label rule (core logic), rerun on the final head.

## 10. Frozen contracts and compatibility

- `RouteSummary` (public, `decoy_engine.route_summary`): two new members at the end, `declines` and `executed_backends`. Additive, pre-GA; `docs/compatibility-contract.md` gets an entry beside the `native_executed` paragraph (`:103`). `RouteDecline`, `NativeConfigOutlook` and `native_config_outlook` are new public names (census and signature snapshots).
- `quality_metrics["unified_slice_decline"]`: new key, present only when the slice was offered and declined.
- `chunked_route.decline_records`: the code for a kernel-less column changes from `fallback_policy_not_native` or `no_native_kernel_or_pool` to its family code. This changes evidence content, not data. Changelog: `Breaking: chunked_route decline_records name the kernel-less family code for shuffle, geo_generalize, formula and derived kinds, nested, joint_mask, tokenize and per-row faker columns.` The legacy `reroute_reason` string is unchanged.
- A5: a run that today silently reruns on pandas after a foreign lane exception now fails with `unified_slice_unexpected_error`; a typed engine error now surfaces with its own code instead of being rerun. Changelog: `Breaking: an unexpected error in the unified-slice lane fails the run instead of rerunning on pandas; rerun with --no-native to bypass the lane.`
- `NodeRequirements.rejection` and `PhysicalNode.decline_code`: internal types, new fields with defaults.
- `decoy explain native` text changes. Not a frozen shape.
- CLI `decoy run` card and `--json`: label strings change (`pandas (streamed lane)` becomes `native lane (Arrow, no compiled kernel)` for Arrow-only lane runs); `native_route.decline` is a new optional member; `native_route.state` keeps its three values. CLI changelog: `Breaking: the run card route label reads the backend each column ran on.`
- `decoy validate` preflight `native.eligibility` message text changes (it names the code). Not a frozen shape.
- Output data bytes: unchanged on every route (E11).

## 11. Pre-mortem

- A decline code is chosen at a site that is not the real cause (for example the identity check reports a type problem). Each site gets its own code, and E1 and E2 cover one case per site.
- A5 turns a latent lane bug into failed runs for users. Accepted and intended (fail closed); the error names the table, the exception class and `--no-native`. Typed engine errors keep their own code, so only foreign exceptions change exit. The zero-count check in guarantee 8 runs on T3 and prod-sim before merge.
- `needs_companion` is wrong for a node the compiler rejects. It reads `requirements_for` per node, the same call the lane uses, and C4 keeps the random-categorical case.
- `native_config_outlook` drifts from `cheap_admission` if someone adds a config check inline. E9 spies that the call happens; the class-9 mutation proves the test notices an inline copy.
- A multi-table run with many declining tables makes a long card. Only the first is printed, with a count.
- The label table gets a wrong case when PER-COLUMN-ROUTING adds Python columns to a lane. The mixed row is in the rule now, and that plan's acceptance tests check the label.

## 12. Open questions for the owner

Both answered at plan gate R1 (2026-11-22):

1. **A5 behavior.** Agreed: fail closed on foreign exceptions only, with the `DecoyError` and `MemoryError` carve-out (guarantee 8).
2. **Label words.** Agreed: `native lane (Arrow, no compiled kernel)` and `mixed (native and Python columns)`, with `decoy explain native` updated to match.

No open questions remain.
