Status: plan (revision 3, 2026-11-21; Dennis rounds 1 and 2 remediated, Codex build-readiness review GO, see section 15)

# NATIVE-MISSING-WARN: one stderr warning when a run used no compiled kernel because the companion is missing

Owner: Cam. Author: Opus plan agent. Date: 2026-11-21. Roadmap row: NATIVE-MISSING-WARN (CLI `docs/roadmap/groups/run.md:25`). Source record: `docs/records/2026-11-19-engine-speed-and-route-completeness.md` (engine #715), section 5.1 M3, section 8 Q6 (owner: pip installs stay bundle-only and get this warning in V1; a `native` extra is PIP-NATIVE-EXTRA, 1.x) and section 10 class 1.

Anchors: a path with no prefix is in this repository (decoy-engine). `C:` is the decoy CLI. Read at engine `origin/main` `035543388` (v0.28.2 plus 10 commits) and CLI `origin/main` `8d17419c`. Line numbers are at those heads.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN contract), `profiles/local-operations.md`, `feature-dev.md`, `bugfix.md`, `api-and-compatibility.md`, `cross-cutting-concerns.md`, `architecture.md` (layout), `security.md` (value-free messages), `testing.md` (test depth, full-suite triggers), `code-review.md`, `reuse-first.md`, `proportionality.md`, `scope-discipline.md`, `verification.md`, `documentation.md`, `workspace-and-vcs.md` (commit rule), and `catalogs/recurring-defects.md`. Engine and CLI `CODEMAP.md` "Where Things Go", engine `tests/sentry/test_module_size.py`, `tests/sentry/layout/test_package_fanout.py`, `docs/compatibility-contract.md` (the SAMPLE SE2 additive-field paragraph at `:113`), `changelog.d/README.md`.

Risk: E1 is R2 (adds a field to the frozen `ExecutionResult`; runs on every `run_pipeline` call). C1 is R1 (one CLI message, one removed hint). Plan review: Dennis, then Codex. Code gate: E1 Dennis then Codex. C1 Codex.

## 1. Frame

### 1.1 Evidence (re-anchored at `035543388`)

- A pip install of the CLI has no companion. The CLI `pyproject.toml` has no `native` extra (`C:pyproject.toml:231-234`). The engine then runs every kernel-backed operator in Python, about 3 times slower (record section 2.5).
- The only message today is a pre-run hint, and only for a unified-slice candidate. `C:src/decoy/_native_gate.py:368-375` returns `info_message` when `status.reason == "absent"`, and `C:src/decoy/cli/run/_prepare.py:564-568` prints it as `native:`. The guard at `C:src/decoy/_native_gate.py:364` returns early for a vault run, a chunked or generate run, and a config that fails `static_native_eligibility`. So a large table on the auto-chunk lane, an FK job on SEQ or OOC, or a config with one Python-only column gets no message.
- The engine knows which kernels a plan needs. `OperatorSpec.required_kernel` (`src/decoy_engine/execution/_operator_registry.py:75`) names `crypto`, `index`, `raw_hex` or `fpe` for hash, faker, categorical, bucket_perturb, group_key, date_shift and fpe (`:195` to `:265`). `native_kernel_availability()` (`src/decoy_engine/execution/native/_companion_status.py:409-436`) reports each kernel and never raises. The compiled plan holds each column's strategy (`ColumnSeed.strategy`, `src/decoy_engine/plan/_types.py:84`, grouped in `TableSeed.per_column`, `:182`).
- Every route returns through one line: `result = _dispatch.execute_route(ctx, decision, refusals)` and then `return stage.stamp(result)` (`src/decoy_engine/execution/_pipeline.py:357-360`), with `ctx.plan` in scope (`src/decoy_engine/execution/_pipeline_context.py:92`).
- `warnings.warn` is the wrong channel. The CLI library path already rejected it for this exact case: `C:src/decoy/api.py:583-591` (M4 remediation) says a `warnings.warn` for the absent companion raises under a caller's `-W error`. The engine's residency warning made the same call (`src/decoy_engine/execution/_residency_warning.py:13-19`).
- `ExecutionResult.warnings` and `quality_metrics` reach the result document, so the row rules both out. `ExecutionResult` already has a field kept out of `repr` and out of the document: `sample_source_rows` (`src/decoy_engine/execution/_adapter.py:78`, compatibility contract `:113`). The field list is pinned by `tests/unit/execution/test_r3_public_signature_freeze.py:126-137`.

### 1.2 The guarantee

- G1. A `decoy run` (default native intent, not `--chunked`, not `--quiet`) prints exactly one line on stderr when its compiled plan needs at least one compiled kernel and none of those kernels is available. The line is `warning: `, the registered summary of `native_companion_missing`, and the CLI's install hint.
- G2. Outputs, the result document and the exit code are byte-identical to the same run today. The warning is not in `quality_metrics`, `ExecutionResult.warnings`, the run record or any JSON output.
- G3. No warning when at least one needed kernel ran, when the plan needs no kernel (redact, truncate, passthrough, shuffle and other Python-only strategies), under `--no-native`, under `--chunked`, or under `--quiet`.
- G4. The message carries no value, path, table or column name.
- G5. The pre-run `native:` hint for an absent companion is removed, so one cause never prints two messages.

Non-goals: a pip `native` extra (PIP-NATIVE-EXTRA); a warning from `decoy.mask()` (the M4 rule keeps the library quiet); text_redact and text_mask only configs (section 5).

## 2. Established solutions

Search run: codebase search in the engine and the CLI for existing notices, result channels and the earlier `warnings.warn` attempt. No external web search was run; the pattern below is standard library practice and the codebase already holds two precedents.

| Source | What it does | Used here |
|---|---|---|
| Python `warnings` module | Category-filtered warnings that `-W error` turns into exceptions | Rejected as the channel, per the CLI M4 finding (`C:src/decoy/api.py:583-591`) |
| pandas optional-accelerator hints (`numexpr`, `bottleneck`) | The library reports a capability; the application decides to print | The engine reports a code on the result; the CLI prints |
| Engine SAMPLE SE2 field (`docs/compatibility-contract.md:113`) | A result field hidden from `repr` and never written | Same shape for the new field |

Custom code left: one 45-line pure function, because the rule needs the engine's operator registry.

## 3. Design

### 3.1 Engine (E1)

New private module `src/decoy_engine/execution/pipeline/_native_notice.py` (about 45 lines):

```python
def native_fallback_code(plan: Plan, availability: KernelAvailability | None = None) -> str | None:
    """`native_companion_missing` when the plan needs a compiled kernel and none of the kernels
    it needs is available; else None."""
```

- `needed` is the set of `operator_spec(seed.strategy).required_kernel` over every `ColumnSeed` in the plan whose strategy is in `OPERATORS` and whose `required_kernel` is not None.
- `needed` empty: return None and do not probe.
- Else probe `native_kernel_availability()` once (or use the injected `availability`). Return the code when no kernel in `needed` is available.

`ExecutionResult` gains `native_fallback_code: str | None = field(default=None, repr=False, compare=False)` as its last field, after `publication_receipt` (`src/decoy_engine/execution/_adapter.py:81`). `run_pipeline` sets it once, after `execute_route` and before `stage.stamp` (`_pipeline.py:359`), with `dataclasses.replace`. No route module changes.

New reason in `src/decoy_engine/reasons/warning/_part1.py` (133 lines today): add `NATIVE_COMPANION_MISSING` to that module's `__all__`, then register `NATIVE_COMPANION_MISSING = _d("native_companion_missing", "No compiled kernel ran: a native kernel this run needs is not available, so masking ran in Python.", since=UNRELEASED)`. Registration through the existing `_d = _catalog.warning("QualityWarning")` declarer is required; this creates the catalog entry and does not emit a `QualityWarning` instance.

The field is set after `execute_route`, so a run refused before it starts never reports a fallback.

### 3.2 CLI (C1, after an engine release that carries E1 and the re-pin)

- `C:src/decoy/cli/run/_execute.py`, immediately after the normal run's `ctx._execution = result` (`:390`), checks the notice inline at its only applicable call site. It does not add the check after the preview assignment at `:442`: `prepare_preview()` sets no `native_intent`, a preview has no mask table, and E1 produces no fallback code for it. At the normal site, return without printing unless `ctx.native_intent == "default"`, the mode is not quiet, and `getattr(result, "native_fallback_code", None)` resolves through the public `decoy_engine.reasons.find("warning", code)` registry. A missing attribute or unknown code is ignored, preserving older-engine and future-skew compatibility. For the registered code print one line on `ctx.state.err_console` with `warn("warning:")`, the registered summary, and the fixed hint "Compiled kernels come with the signed bundle; run `decoy explain native` to see what is missing." The hint does not say "not installed", because a present companion can lack one kernel or fail its probe. The hint is one constant in `C:src/decoy/_native_gate.py`.
- `C:src/decoy/_native_gate.py:368-375`: the default-intent absent branch returns `PreGateResult(unified_slice_enabled=True)` with no `info_message`. The `require` and broken-companion branches stay.
- `C:src/decoy/api.py` (`decoy.mask()`): no behaviour change. A library caller can read the field. The comment at `C:src/decoy/api.py:583-589` is reworded: the absent companion is now reported after the run through `ExecutionResult.native_fallback_code`, and the library still never calls `warnings.warn` for it.
- Kept, with reasons: the `PreGateResult.info_message` field (`C:src/decoy/_native_gate.py:106`) and its print (`C:src/decoy/cli/run/_prepare.py:564-568`). After C1 no branch sets the field, but `C:tests/unit/test_native_gate.py:558`, `:640`, `:649` and `:661` read it, and it is the gate's only hint channel. Removing a dataclass field and its print is cleanup, not this row. V2-LOG line: "remove the unused `PreGateResult.info_message` and its print".

### 3.3 Design notes

- New structure: one private module with one function. Principle: single responsibility. The change pain it removes: without it the CLI would need its own copy of the strategy-to-kernel map (the CLI already keeps one such copy, `C:src/decoy/_native_gate.py:57-80`, and the record lists that as a drift risk).
- Each fact has one place: the kernel per strategy stays in `OPERATORS`; availability stays in `native_kernel_availability`; the text stays in the reasons registry; the decision lives only in `native_fallback_code`.
- No flag argument. `availability` is a test seam with a default, not a behaviour switch.

## 4. Behaviour

| Case | Today | After E1 and C1 |
|---|---|---|
| pip install, 10-row hash config (unified-slice candidate) | `native:` hint before the run | one `warning:` line after the run, no hint |
| pip install, 200k-row hash table (auto-chunk lane) | no message | one `warning:` line |
| pip install, FK job with hash keys (OOC or SEQ) | no message | one `warning:` line |
| pip install, redact and truncate only | no message | no message |
| pip install, `--no-native` | no message | no message |
| pip install, `--chunked` | no message | no message (the chunked path runs no kernel, G3) |
| pip install, `--quiet` | no hint | no warning |
| bundle install, healthy companion | no message | no message |
| companion missing only `raw_hex`, hash plus group_key | no message | no message (another needed kernel is available). On the unified-slice route admission needs every kernel of the table (`_unified_slice_admission.py:550-553`), so that table can run in Python with no notice. Partial companions only; V2-LOG: decide per table, as admission does |
| companion missing only `raw_hex`, group_key only | no message | one `warning:` line |
| present but broken companion, default intent | refused before the run (`C:src/decoy/_native_gate.py:376-385`) | unchanged |
| run refused at plan compile | refusal only | refusal only |

## 5. Failure modes

| Case | Behaviour |
|---|---|
| `native_kernel_availability()` raises | It cannot: it catches every import and KAT failure (`_companion_status.py:416-436`) |
| Strategy not in `OPERATORS` (for example `shuffle`) | Not counted in `needed` |
| Generate-only plan | No mask `ColumnSeed`, `needed` empty, no probe |
| `run_pipeline_isolated` | Out of scope. `IsolatedRunResult` (`src/decoy_engine/execution/_isolated_common.py:401`) is rebuilt field by field, in process (`src/decoy_engine/execution/_isolated_run.py:335-348`) and from the child envelope (`:581-595`), so the field is not carried. The CLI never calls this entry. V2-LOG line: "carry `native_fallback_code` on `IsolatedRunResult`" |
| Older engine under a newer CLI | `getattr(..., None)` reads None, no warning |
| text_redact or text_mask only | `required_kernel` is None for both (`_operator_registry.py:167`, `:178`), so no warning. Accepted V1 gap, V2-LOG line in section 12 |

## 6. Choke point and sentries

One rule, one choke point: `native_fallback_code` in `execution/pipeline/_native_notice.py`, called once from `run_pipeline` after `execute_route`. The CLI prints only what the field says. Guard test: AT-2 runs four routes through `run_pipeline` and fails when any route returns without the field. Mutation: move the call into one route (the unified slice) and AT-2 goes red on the other three.

### 6.1 Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the warning line | the line is the registry summary plus a CLI constant; the engine field holds a registered code only | AT-3, AT-C3 | put the table name into the CLI line; return free text from `native_fallback_code` |
| 2 | Cleanup on exit path | none | N/A: no file, stage or handle is opened; the probe is read-only | n/a | n/a |
| 3 | State and concurrency | none | N/A: one pure function per run; no cache and no shared state is added | n/a | n/a |
| 4 | Route parity and silent fallback | every route of `run_pipeline` | the field is set after the one `execute_route` call, not inside a route | AT-2 (unified, auto-chunk, SEQ, OOC) | set the field inside the unified-slice route only |
| 5 | Referential integrity | none | N/A: no key, join or FK value is read or written | n/a | n/a |
| 6 | Untrusted producer | none | N/A: no new input boundary; the probe exists and never raises | n/a | n/a |
| 7 | Check then use (TOCTOU) | none | N/A: the probe result is advisory and drives no data path | n/a | n/a |
| 8 | Weak tests | a test that passes because the node has the companion | AT-1, AT-2 and AT-7 inject `KernelAvailability` instead of reading the host | AT-1, AT-2, AT-7 | drop the injection and let the host decide |
| 9 | Refactor drift | the pre-run hint removed in C1 | AT-C2 asserts no `native:` line | AT-C2 | keep the old hint |
| 10 | Frozen contract drift | `ExecutionResult` fields; result document bytes | additive field hidden from `repr`, not compared; compat note; AT-5 pins the document | AT-4, AT-5 | add the field with `repr=True`; stamp the code into `quality_metrics` |

### 6.2 Enumerations

#### Exit paths

- Normal return of `run_pipeline`: field set (`src/decoy_engine/execution/_pipeline.py:359`).
- Refusal before or inside `execute_route`: exception, no field, no warning.
- CLI `post_run_verify` refusal under `--native` (`C:src/decoy/_native_gate.py:450-464`): `require` intent, so C1 never prints.

#### Routes

- Unified slice, auto-chunk lane, multi-table split, SEQ, OOC, mixed and the full-frame oracle all return through `execute_route` (`src/decoy_engine/execution/_pipeline.py:359`), so the one call covers them.
- `--chunked` (`C:src/decoy/cli/run/_execute.py:333-347`) does not call `run_pipeline`; no warning by design (G3).
- `run_mask_chunked`, a public entry outside `run_pipeline`: out of scope. It already reports `compiled_kernel_executed`.

#### FK shapes

- N/A for the rule: it reads strategies only, never keys. FK jobs take the same path as non-FK jobs.
- AT-2 includes one single-parent FK fixture on SEQ and on OOC; self-reference and cycle jobs route to SEQ or full-frame and still pass `execute_route`.

#### Fields

- `ExecutionResult.native_fallback_code`: `str | None`, default None, `repr=False`, `compare=False`, last field.
- Reason `warning/native_companion_missing`, `since=UNRELEASED` until the release stamps it.

#### Output surfaces

- New: one stderr line in the CLI.
- Unchanged: result document, run record, JSON output, `quality_metrics`, `ExecutionResult.warnings` (AT-5).
- Removed: the pre-run `native:` hint on stderr (C1).

## 7a. Reuse inventory

| Need | Reused | Changed |
|---|---|---|
| Which kernel a strategy needs | `OPERATORS`, `operator_spec` (`_operator_registry.py:288-295`) | none |
| Whether a kernel is present | `native_kernel_availability()` | none |
| Existing not-installed reader | `route_summary()` sets `native == NATIVE_NOT_INSTALLED` and `native_executed` (`src/decoy_engine/execution/pipeline/_route_summary.py:24-31`, `:119-155`); CLI `classify_route` reads it (`C:src/decoy/_native_gate.py:427-435`) | none; AT-8 checks the two agree |
| Message text | reasons registry (`reasons/warning/_part1.py`) | one new reason |
| Hidden result field | SAMPLE SE2 pattern (`_adapter.py:78`) | one new field |
| CLI warning style | `warn("warning:")` on `err_console` (`C:src/decoy/cli/run/_prepare.py:569-570`) | none |

Why a static predicate and not `route_summary()`: `route_summary` reads lane evidence only (`auto_chunk`, `chunked_route`, the multi-table split and the mixed route, `_route_summary.py:95-117`). SEQ and OOC write no lane evidence, so it returns `native=None` and `native_executed=None` there, and the unified slice records `unified_slice_activation` instead. A pip-install FK job would get no warning. The plan-and-probe predicate gives the same answer on every route. AT-8 pins agreement where both apply.

## 7. Acceptance tests, red first

Each test below fails on `035543388` (the function and field do not exist) and passes after the slice.

Engine, `tests/unit/execution/pipeline/test_native_fallback_notice.py` (new, about 140 lines):

Patch target for AT-1, AT-2 and AT-7: `decoy_engine.execution.pipeline._native_notice.native_kernel_availability`. The module imports the function by name and calls it through its own module attribute, so patching that attribute replaces the probe.

- AT-1: `native_fallback_code` returns the code for a hash plan with all-False availability; None with `crypto=True`; None for a redact-only plan, and the probe is not called (spy).
- AT-2: `run_pipeline` with the probe patched all-False sets the field on four fixtures: a 10-row hash table (unified slice), a hash table over a lowered `auto_chunk_threshold_rows` (auto-chunk lane), and a parent and child with hash keys under `execution_mode="sequential"` and under `"out_of_core"`.
- AT-3: the field is exactly `reasons.warning.NATIVE_COMPANION_MISSING.code`; the summary is exactly "No compiled kernel ran: a native kernel this run needs is not available, so masking ran in Python."; the reason passes the existing reason registry sentries.
- AT-4: `FROZEN_RESULT_FIELDS` in `test_r3_public_signature_freeze.py` gains `("native_fallback_code", "None", False, False)` as its last row.
- AT-5: the same hash fixture run with the probe all-False and all-True gives equal `outputs`, equal `quality_metrics` and an equal projected run result, and the serialized run result contains no `native_companion_missing` string.
- AT-6: dropped in revision 2. The isolated entry rebuilds its result field by field, so it cannot carry the field, and the CLI never calls it (section 5, V2-LOG).
- AT-7: partial companion, `raw_hex=False` and the rest True. Hash plus group_key: None. group_key only: the code.
- AT-8: agreement on an auto-chunk run using the real, unpatched `native_kernel_availability()` probe that the lane also reads. Assert both directions as one equivalence: `result.native_fallback_code is not None` exactly when `route_summary(result.quality_metrics).native == "not_installed"`. Do not predict the host state in the test. Add this test file to the explicit pytest selections in `.github/workflows/native-companion.yml` jobs `core-companion-absent` (the no-native-extra state) and `core-companion-present`, so the same equivalence runs with no companion and with the built companion.
- AT-9: a mixed job (a generate table with a faker column, plus a mask table with redact only) gives None with the probe all-False: generate columns do not count.

CLI, `C:tests/e2e/run_native/test_missing_warn.py` (new, about 90 lines, with `C:tests/e2e/run_native/__init__.py`), with the field set on a faked result:

- AT-C1: default intent, field set: exactly one stderr line starts with `warning:`. Run the same fixture with the field set and with it None under `--json --no-library`, parse both envelopes, and normalize only the volatile fields before equality: top-level `elapsed_s`; `result.invocation_id`; `result.timings.started_at`, `finished_at` and `elapsed_s`; every `result.timings.phases[*].elapsed_s`; and every `result.tables[*].elapsed_s`. The remaining stdout JSON, including outputs, warnings, result document and exit data, is equal.
- AT-C2: absent companion: no `native:` line before the run.
- AT-C3: the line has no table, column or source path from the fixture.
- AT-C4: `--no-native`, `--chunked` and `--quiet` print nothing.
- AT-C5: a result without the attribute prints nothing; a `--rows` preview remains unchanged and prints no native fallback notice.
- AT-C6: an unknown `native_fallback_code` does not raise and prints nothing.

Mutations (each must turn a named test red): remove the call at `_pipeline.py` (AT-2); return the code when any one needed kernel is missing instead of all (AT-7); probe before the `needed` check (AT-1 spy); set `repr=True` (AT-4); print in the CLI without the intent check (AT-C4).

### 7b. Existing tests that change

- `tests/unit/execution/test_r3_public_signature_freeze.py:126-137` (AT-4).
- `C:tests/unit/test_native_gate.py:651-662` (`test_default_on_eligible_shape_with_absent_companion_hints_install`): it asserts `info_message is not None` and "decoy explain native". After C1 it asserts `info_message is None` for the absent companion. Rename it to say the gate is silent.

## 8. Placement

| New or changed file | Directory | CODEMAP "Where Things Go" line | Sits beside |
|---|---|---|---|
| `_native_notice.py` (new, about 45 lines) | `src/decoy_engine/execution/pipeline/` (16 entries) | "Pipeline spine and routes": new route clusters in `execution/pipeline/`. Not `execution/native/`, which is at its fan-out freeze of 55 | `_route_summary.py`, `_host.py` |
| `_adapter.py` (528 lines, plus 3) | `src/decoy_engine/execution/` | "Pipeline spine and routes" | existing |
| `_pipeline.py` (360 lines, plus 3) | `src/decoy_engine/execution/` | "Pipeline spine and routes" | existing |
| `reasons/warning/_part1.py` (133 lines, plus 5) | `src/decoy_engine/reasons/warning/` | "Reason codes" | existing |
| `test_native_fallback_notice.py` (new) | `tests/unit/execution/pipeline/` | "Pipeline spine and routes" tests; the flat `tests/unit/execution/` folder has 275 direct entries and takes no new module | `test_lifecycle.py` |
| `native-companion.yml` (changed) | `.github/workflows/` | CI workflow convention; existing two-state companion matrix | existing `core-companion-absent` and `core-companion-present` jobs |
| `native-missing-warn.md` (new) | `changelog.d/` | "Changelog fragments" | existing fragments |
| compat note | `docs/compatibility-contract.md`, beside `:113` | "Feature and contract docs" | SAMPLE SE2 paragraph |
| CLI print and hint removal | `C:src/decoy/cli/run/_execute.py`, `C:src/decoy/_native_gate.py` | CLI layout | existing |
| `C:tests/e2e/run_native/__init__.py`, `test_missing_warn.py` (new) | `C:tests/e2e/run_native/` | CLI CODEMAP "decoy run internals" tests go under `tests/e2e/`; a named package avoids adding to the 109-entry flat folder | `C:tests/e2e/test_run_native.py` |

No module crosses the module-size GOAL of 600 lines, so the census needs no entry.

## 9. Frozen contracts touched

- `ExecutionResult` field list (pinned by the R3 freeze test): one additive field, default None, hidden from `repr`, not compared. Pre-GA additive, the same class as SAMPLE SE2. Compat note text: "`ExecutionResult.native_fallback_code: str | None` (default None, hidden from `repr`, not compared) is `native_companion_missing` when the plan needs a compiled kernel and none that it needs is available. It is never written to a document."
- Result document and run record: unchanged (AT-5).
- One new reason code, pending until the release.

Full-suite trigger: yes for E1 (frozen contract, the `ExecutionResult` field list). C1: no trigger (CLI message text and one removed hint), so T1 plus the T2 gate set.

## 10. Slices

| Slice | Repo | Content | Size | Risk | Gate |
|---|---|---|---|---|---|
| E1 | engine | module, field, call, reason, tests, two CI selections, changelog fragment, compat note | about 210 lines with tests; 1 new public field, 1 new reason | R2 | Dennis then Codex; full suite on the merge head |
| C1 | CLI | one normal-run print site, hint removal, tests | about 120 lines with tests | R1 | Codex; T1 plus the T2 set |

C1 waits on an engine release that carries E1 and the CLI re-pin (engine re-pin checklist).

## 11. Stop lines for builders

- Do not call `warnings.warn` or emit a `QualityWarning` instance for this signal. Registering the reason through `_part1.py`'s existing `_d = _catalog.warning("QualityWarning")` declarer is required.
- Do not write the code into `quality_metrics` or any document.
- Do not copy the strategy-to-kernel map into the CLI.
- Do not widen or skip an existing test to make the field list pass. Update `FROZEN_RESULT_FIELDS` only.
- Do not delete `test_default_on_eligible_shape_with_absent_companion_hints_install`; change its assertions only.
- Stop and report if a route returns without passing `_pipeline.py:359`. That is a second choke point and a plan change.

## 12. Owner questions (recommended option first)

None blocking. Recorded calls, go with recommended:

1. Q1. Quiet mode: suppress the warning under `--quiet`, as the existing hint does. Recommended: yes.
2. Q2. text_redact and text_mask only configs: no warning in V1. V2-LOG line: "add the span kernel to `OperatorSpec.required_kernel` so the notice covers text configs". Recommended: V2-LOG.

## 13. Pre-mortem

- The R3 freeze test fails on field order: the field goes last, after `publication_receipt`.
- A test node has the companion and AT-2 passes for the wrong reason: availability is injected (class 8).
- Five engine tests turn warnings into errors (`tests/unit/execution/test_ooc_residency_warning.py` and four others). This design emits no Python warning, so they are not affected.
- Probe cost on a bundle install: `native_kernel_availability()` runs four known-answer probes and is not cached. A CLI bundle run pays it twice: once in the CLI pre-run gate (`native_companion_status`) and once in `native_fallback_code`, only when the plan needs a kernel. The builder records the measured time in the PR. V2-LOG line: "cache one companion probe per process".
- A builder reaches for `warnings.warn` because it is shorter: stop line 1.

## 14. Sources

- Record `docs/records/2026-11-19-engine-speed-and-route-completeness.md` sections 2.5, 5.1 M3, 8 Q6, 10 class 1.
- CLI `C:src/decoy/api.py:583-591` (M4 remediation).

## 15. Revision map

### Revision 3 (Dennis round 2 and Codex build-readiness review: GO)

| Finding | Change |
|---|---|
| V1, Dennis HIGH: AT-8 patched only the notice probe while auto-chunk read the real probe | AT-8 now leaves the probe unpatched, asserts the field and `route_summary(...).native == "not_installed"` are equivalent in both directions, and runs in the explicit companion-absent and companion-present CI jobs |
| V2-LOG, Dennis LOW: compat text said "installed" instead of "available" | Compatibility text now uses "available" |
| V2-LOG, Dennis LOW: AT-C1 compared volatile run records without naming normalization | AT-C1 now names the invocation id, timestamps and every duration field it normalizes before comparison |
| V2-LOG, Dennis LOW: the `QualityWarning` stop line contradicted required reason registration and omitted `__all__` | The stop line distinguishes catalog registration from instance emission; E1 adds the name to `_part1.py` `__all__` |
| DESIGN: both new tests were proposed in flat folders already far beyond the direct-module limit | The engine test moves under existing `tests/unit/execution/pipeline/`; the CLI test gets the named `tests/e2e/run_native/` package; the Placement table names both |
| V1: C1 also targeted the preview assignment, but `prepare_preview()` never initializes `native_intent` | The print check now exists only after the normal run assignment at `C:_execute.py:390`; AT-C5 pins preview unchanged |
| V1: an unknown future reason code could make the CLI dereference a missing registry entry | C1 ignores an unknown code; AT-C6 pins no crash and no output |

### Revision 2 (Dennis round 1: BLOCK, 0 critical, 2 high, 2 medium, 3 low)

| Finding | Change |
|---|---|
| HIGH 1: `IsolatedRunResult` drops the field, AT-6 cannot pass | AT-6 dropped with a written reason; isolated path out of scope in section 5; V2-LOG line |
| HIGH 2: an existing not-installed reader is not named | `route_summary` and `classify_route` named in 7a; why a static predicate (SEQ and OOC write no lane evidence); AT-8 agreement test |
| MEDIUM 3: "not installed" is false for a partial or broken companion | reason summary and CLI hint reworded; AT-3 pins the text |
| MEDIUM 4: an existing CLI test asserts the hint | `C:tests/unit/test_native_gate.py:651-662` listed in 7b; stop line against deleting it |
| LOW 5: dead `info_message` | kept with reasons; `api.py` comment reworded; V2-LOG line |
| LOW 6: test details | patch target named; AT-5 checks the serialized result; AT-9 mixed job; AT-C1 JSON baseline |
| LOW 7: probe cost | recorded in section 13; V2-LOG line for one cached probe per process |
