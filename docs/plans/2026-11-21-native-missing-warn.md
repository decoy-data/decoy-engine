Status: plan

# NATIVE-MISSING-WARN: one stderr warning when a run used no compiled kernel because the companion is missing

Owner: Cam. Author: Opus plan agent. Date: 2026-11-21. Roadmap row: NATIVE-MISSING-WARN (CLI `docs/roadmap/groups/run.md:25`). Source record: `docs/records/2026-11-19-engine-speed-and-route-completeness.md` (engine #715), section 5.1 M3, section 8 Q6 (owner: pip installs stay bundle-only and get this warning in V1; a `native` extra is PIP-NATIVE-EXTRA, 1.x) and section 10 class 1.

Anchors: a path with no prefix is in this repository (decoy-engine). `C:` is the decoy CLI. Read at engine `origin/main` `035543388` (v0.28.2 plus 10 commits) and CLI `origin/main` `8d17419c`. Line numbers are at those heads.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN contract), `feature-dev.md`, `api-and-compatibility.md`, `cross-cutting-concerns.md`, `architecture.md` (layout), `security.md` (value-free messages), `testing.md` (test depth, full-suite triggers), `reuse-first.md`, `proportionality.md`, `scope-discipline.md`, `documentation.md`, `workspace-and-vcs.md` (commit rule). Engine `CODEMAP.md` "Where Things Go", `tests/sentry/test_module_size.py`, `tests/sentry/layout/test_package_fanout.py`, `docs/compatibility-contract.md` (the SAMPLE SE2 additive-field paragraph at `:113`), `changelog.d/README.md`.

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

New reason in `src/decoy_engine/reasons/warning/_part1.py` (133 lines today): `NATIVE_COMPANION_MISSING = _d("native_companion_missing", "No compiled kernel ran: the native companion is not installed, so masking ran in Python.", since=UNRELEASED)`.

The field is set after `execute_route`, so a run refused before it starts never reports a fallback.

### 3.2 CLI (C1, after an engine release that carries E1 and the re-pin)

- `C:src/decoy/cli/run/_execute.py`, after `ctx._execution = result` (`:390` and `:442`): when `ctx.native_intent == "default"`, `getattr(result, "native_fallback_code", None)` is set and the mode is not quiet, print one line on `ctx.state.err_console` with `warn("warning:")`, the summary from `decoy_engine.reasons.find("warning", code)`, and the fixed hint "Install the signed bundle for compiled kernels; see `decoy explain native`." The hint is one constant in `C:src/decoy/_native_gate.py`.
- `C:src/decoy/_native_gate.py:368-375`: the default-intent absent branch returns `PreGateResult(unified_slice_enabled=True)` with no `info_message`. The `require` and broken-companion branches stay.
- `C:src/decoy/api.py` (`decoy.mask()`): unchanged. A library caller can read the field.

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
| companion missing only `raw_hex`, hash plus group_key | no message | no message (hash ran native) |
| companion missing only `raw_hex`, group_key only | no message | one `warning:` line |
| present but broken companion, default intent | refused before the run (`C:src/decoy/_native_gate.py:376-385`) | unchanged |
| run refused at plan compile | refusal only | refusal only |

## 5. Failure modes

| Case | Behaviour |
|---|---|
| `native_kernel_availability()` raises | It cannot: it catches every import and KAT failure (`_companion_status.py:416-436`) |
| Strategy not in `OPERATORS` (for example `shuffle`) | Not counted in `needed` |
| Generate-only plan | No mask `ColumnSeed`, `needed` empty, no probe |
| `run_pipeline_isolated` | The child sets the field and the returned result carries it (AT-6) |
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
| Message text | reasons registry (`reasons/warning/_part1.py`) | one new reason |
| Hidden result field | SAMPLE SE2 pattern (`_adapter.py:78`) | one new field |
| CLI warning style | `warn("warning:")` on `err_console` (`C:src/decoy/cli/run/_prepare.py:569-570`) | none |

## 7. Acceptance tests, red first

Each test below fails on `035543388` (the function and field do not exist) and passes after the slice.

Engine, `tests/unit/execution/test_native_fallback_notice.py` (new, about 140 lines):

- AT-1: `native_fallback_code` returns the code for a hash plan with all-False availability; None with `crypto=True`; None for a redact-only plan, and the probe is not called (spy).
- AT-2: `run_pipeline` with the probe patched all-False sets the field on four fixtures: a 10-row hash table (unified slice), a hash table over a lowered `auto_chunk_threshold_rows` (auto-chunk lane), and a parent and child with hash keys under `execution_mode="sequential"` and under `"out_of_core"`.
- AT-3: the field is exactly `reasons.warning.NATIVE_COMPANION_MISSING.code`, and the reason passes the existing reason registry sentries.
- AT-4: `FROZEN_RESULT_FIELDS` in `test_r3_public_signature_freeze.py` gains `("native_fallback_code", "None", False, False)` as its last row.
- AT-5: the same hash fixture run with the probe all-False and all-True gives equal `outputs`, equal `quality_metrics` and an equal projected run result.
- AT-6: `run_pipeline_isolated` (no memory cap) returns the field set.
- AT-7: partial companion, `raw_hex=False` and the rest True. Hash plus group_key: None. group_key only: the code.

CLI, `C:tests/cli/test_run_native_missing_warn.py` (new, about 90 lines), with the field set on a faked result:

- AT-C1: default intent, field set: exactly one stderr line that starts with `warning:`; stdout and the JSON record unchanged.
- AT-C2: absent companion: no `native:` line before the run.
- AT-C3: the line has no table, column or source path from the fixture.
- AT-C4: `--no-native`, `--chunked` and `--quiet` print nothing.
- AT-C5: a result without the attribute prints nothing.

Mutations (each must turn a named test red): remove the call at `_pipeline.py` (AT-2); return the code when any one needed kernel is missing instead of all (AT-7); probe before the `needed` check (AT-1 spy); set `repr=True` (AT-4); print in the CLI without the intent check (AT-C4).

### 7b. Existing tests that change

- `tests/unit/execution/test_r3_public_signature_freeze.py:126-137` (AT-4).
- CLI tests that assert the absent hint text "native acceleration is not installed": a grep of `C:tests/` at `8d17419c` finds none.

## 8. Placement

| New or changed file | Directory | CODEMAP "Where Things Go" line | Sits beside |
|---|---|---|---|
| `_native_notice.py` (new, about 45 lines) | `src/decoy_engine/execution/pipeline/` (16 entries) | "Pipeline spine and routes": new route clusters in `execution/pipeline/`. Not `execution/native/`, which is at its fan-out freeze of 55 | `_route_summary.py`, `_host.py` |
| `_adapter.py` (528 lines, plus 3) | `src/decoy_engine/execution/` | "Pipeline spine and routes" | existing |
| `_pipeline.py` (360 lines, plus 3) | `src/decoy_engine/execution/` | "Pipeline spine and routes" | existing |
| `reasons/warning/_part1.py` (133 lines, plus 5) | `src/decoy_engine/reasons/warning/` | "Reason codes" | existing |
| `test_native_fallback_notice.py` (new) | `tests/unit/execution/` | "Unit tests" | `test_r3_public_signature_freeze.py` |
| `native-missing-warn.md` (new) | `changelog.d/` | "Changelog fragments" | existing fragments |
| compat note | `docs/compatibility-contract.md`, beside `:113` | "Feature and contract docs" | SAMPLE SE2 paragraph |
| CLI print and hint removal | `C:src/decoy/cli/run/_execute.py`, `C:src/decoy/_native_gate.py` | CLI layout | existing |

No module crosses the module-size GOAL of 600 lines, so the census needs no entry.

## 9. Frozen contracts touched

- `ExecutionResult` field list (pinned by the R3 freeze test): one additive field, default None, hidden from `repr`, not compared. Pre-GA additive, the same class as SAMPLE SE2. Compat note text: "`ExecutionResult.native_fallback_code: str | None` (default None, hidden from `repr`, not compared) is `native_companion_missing` when the plan needs a compiled kernel and none that it needs is installed. It is never written to a document."
- Result document and run record: unchanged (AT-5).
- One new reason code, pending until the release.

Full-suite trigger: yes for E1 (frozen contract, the `ExecutionResult` field list). C1: no trigger (CLI message text and one removed hint), so T1 plus the T2 gate set.

## 10. Slices

| Slice | Repo | Content | Size | Risk | Gate |
|---|---|---|---|---|---|
| E1 | engine | module, field, call, reason, tests, changelog fragment, compat note | about 200 lines with tests; 1 new public field, 1 new reason | R2 | Dennis then Codex; full suite on the merge head |
| C1 | CLI | print, hint removal, tests | about 120 lines with tests | R1 | Codex; T1 plus the T2 set |

C1 waits on an engine release that carries E1 and the CLI re-pin (engine re-pin checklist).

## 11. Stop lines for builders

- Do not use `warnings.warn` or `QualityWarning` for this signal.
- Do not write the code into `quality_metrics` or any document.
- Do not copy the strategy-to-kernel map into the CLI.
- Do not widen or skip an existing test to make the field list pass. Update `FROZEN_RESULT_FIELDS` only.
- Stop and report if a route returns without passing `_pipeline.py:359`. That is a second choke point and a plan change.

## 12. Owner questions (recommended option first)

None blocking. Recorded calls, go with recommended:

1. Q1. Quiet mode: suppress the warning under `--quiet`, as the existing hint does. Recommended: yes.
2. Q2. text_redact and text_mask only configs: no warning in V1. V2-LOG line: "add the span kernel to `OperatorSpec.required_kernel` so the notice covers text configs". Recommended: V2-LOG.

## 13. Pre-mortem

- The R3 freeze test fails on field order: the field goes last, after `publication_receipt`.
- A test node has the companion and AT-2 passes for the wrong reason: availability is injected (class 8).
- Five engine tests turn warnings into errors (`tests/unit/execution/test_ooc_residency_warning.py` and four others). This design emits no Python warning, so they are not affected.
- Probe cost on a bundle install: four known-answer calls once per run, only when the plan needs a kernel. The builder records the measured time in the PR.
- A builder reaches for `warnings.warn` because it is shorter: stop line 1.

## 14. Sources

- Record `docs/records/2026-11-19-engine-speed-and-route-completeness.md` sections 2.5, 5.1 M3, 8 Q6, 10 class 1.
- CLI `C:src/decoy/api.py:583-591` (M4 remediation).
