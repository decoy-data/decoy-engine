Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`, `architecture.md`, `testing.md` (test depth), `cross-cutting-concerns.md`, `proportionality.md`, `api-and-compatibility.md`, `profiles/local-operations.md`, `catalogs/recurring-defects.md` (all 11 classes); vault `10_Projects/decoy/handoffs/LOCAL-BUILDER-BRIEF.md`; engine `CLAUDE.md`, `CODEMAP.md` ("Where Things Go"), `docs/frozen-surfaces.md`, `docs/compatibility-contract.md`; CLI `docs/ROADMAP.md` (rows 24zi, 61, 63a), CLI `CODEMAP.md`; source plan engine `docs/plans/2026-11-16-prop-batch.md` revision 7; engine PR 821 `docs/plans/PROP-SURFACE-WIDE-PLAN.md` (head `d17f909ce`).

# PROP-FALLBACK (row 24zi): quiet fallbacks that weaken output while the run reports success

Status: plan (loop extract of PROP batch revision 7, build-ready on Codex review-low GO at `88b2e0126`; anchors refreshed 2026-11-25)

Row: 24zi PROP-FALLBACK. Risk: R2. Release: engine fixes ship on an engine daily train, then a CLI repin (section 11); CLI 1.0.0 carries the C slices.
Source: engine branch `docs/plans-prop-reanchor-1125` head `031a6a63b`, file `docs/plans/2026-11-16-prop-batch.md`, revision 7. This file is the 24zi part of that plan. The wording is kept; only file:line anchors are refreshed. Rows 24zj, 24zk and 24zl stay in the source plan and are not changed here.
Repo and branch: engine `decoy-data/decoy-engine` and CLI `decoy-data/decoy`. Slice branches are named by the dispatcher. Loop plan worktree `wt-plan-prop-fallback`, branch `plan/prop-fallback` at engine `393f0d47c`.
Bases (verified 2026-11-25): engine `origin/main` `393f0d47c`; CLI `origin/main` `3df9c13a` (pins `decoy-engine==0.28.3`).

Notation: `E:` is engine `src/decoy_engine/`, `ET:` is engine `tests/`, `C:` is CLI `src/decoy/`, `CT:` is CLI `tests/`.

## Changes in round 2

Fix round 1 for the Senior review GO-WITH-FIXES (findings F1 to F9). Bases re-checked 2026-11-25: engine `origin/main` is still `393f0d47c`, CLI `origin/main` is still `3df9c13a`, so no anchor moved. Every new anchor below was read on those commits.

- F1 (reviewer fix). A2's code is `runtime.reference_table_unavailable`, declared in `E:reasons/runtime/_part2.py` in the `_catalog.runtime("ExecutionError")` block beside `TRANSFORM_SOURCE_MISSING` (`:270`). It is raised as `ExecutionError` (`E:_execution_error.py:15`), which `exit_code_for` maps to exit 3 because it is not in `usage_error_types()` (`C:cli/exit_codes.py:288-360`). Section 2 row A2, section 8b "Exit paths" and AT-A2 now agree; AT-A2 asserts code, `decoy run` exit 3, and `__cause__`/`__context__` None.
- F2 (reviewer fix, "list is empty" branch). `build_live_physical_plan_inputs` (`E:execution/physical/_live_inputs.py:47`) has no `raise`, and `compile_physical_plan` (`E:execution/physical/_compiler.py:387`) raises only the oracle's own errors and `AssertionError` (`:272`, `:339`, `:381`). No coded "slice not eligible" raise exists, so `_REROUTABLE` group 1 and the AT-A5c decline cell are deleted. Section 3 now states that oracle-identical refusals propagate.
- F3 (reviewer fix, with a named fix point). The census records each AT-A5b user-error cell's lane type and code beside the oracle's. A mismatch is fixed at the lane's raise site by calling the same constructor the oracle uses (the `E:execution/_errors.py` helper pattern, for example `text_mask_unsupported_pair_error`). If that needs more than the E-F2 budget, the builder stops and reports for a re-scope. Section 3 and AT-A5b.
- F4 (reviewer fix, plus a code-name fix). `TargetTableMissingError(Exception)` carries `code`, like `LayoutError` (`C:cli/io/_layout_errors.py:23`). It is registered in `exit_code_for` (exit 3) with a row in `CT:unit/test_exit_code_for.py`. The code constant sits in `C:cli/io/_target_presence.py`. Its name is `target.table_missing`, under the CLI's existing `target.` prefix (`C:cli/io/_targets.py:57-58`), because the CLI has no `io.` namespace. Tokenize gets its own arm that emits the code and exits through `exit_code_for`. Tokenize also calls `refuse_missing_targets` before `token_vault.commit()` (`C:cli/tokenize.py:373`). Section 8a class 10 now names the real guards.
- F5 (reviewer fix). `shared_destination_findings` (`C:cli/gate/_layers.py:162-182`) becomes `early_schema_findings` over one named tuple, `EARLY_SCHEMA_CODES = (TARGET_SHARED_DESTINATION, TARGET_TABLE_UNKNOWN)`. No second function is added. All three callers move with it: `C:cli/run/_prepare.py:22,294`, `C:cli/compile_explain.py:186-188` and `C:cli/gate/__init__.py:13,42`. `_layers.py` is now a fixed C-F1a file, and AT-A8a has a `--duckdb-source` cell.
- F6 (reviewer fix). `missing_target_tables` covers every declared target, whatever its `type`. AT-A8b gets a cloud cell in C-F1b, which already waits on DELIV C2a.
- F7 (reviewer fix). Section 5 names `approved_growth` (`ET:sentry/_ratchet.py:126-150`, rows in `scripts/dev/sentry_registry.toml`) as the only path for a deliberate new broad-except boundary. It admits a new key only (a raised `max` is refused at `:486-490`), so the plan says where such a boundary must sit. The DELIV and RUN-STREAM amendment notes in section 4 say so.
- F8 (taken). The `_checks.py:637` narrowing names `decoy_engine.errors.ValidationError`. New AT-CHK proves `compile_expr`'s raise set (`E:expressions/_lark_parser.py:79-199`, plus `_validate_string_escapes`, defined at `:225`).
- F9 (taken). A7's import stays inside `_validate_scaffold`. AT-A7 would not exercise a module-level import.

## Changes in this extract

Merged-state check (2026-11-25):

- E-F0 is merged: engine #617 (`89a3ac080`, merged 2026-11-20) is an ancestor of engine main.
- A4 is closed: engine #596 (`8b1330157`, merged 2026-11-21) is an ancestor of engine main. `E:plan/checks/_generate_columns.py` has one `except Exception` left (`:296`, `_check_categories`), which fails closed.
- E-G1 (engine #688) is merged, so E-F1 and E-F2 have their dependency.
- No E-F1, E-F2, C-F1a or C-F1b work is on either main or in an open PR. Engine main has no `_swallowed_except`, `swallowed-broad-except`, `_REROUTABLE`, `config.target_table_unknown` or `transform.reference_table_unavailable`. CLI main has no `missing_target_tables`, `TargetTableMissingError` or `io.target_table_missing`. Open engine PRs with PROP in scope: #821 (24zj plan) and #822 (E-S1a). Open CLI PR: #308 (records only).
- C-F1b is still blocked: CLI main has no `seal_result` (row 63a C1a not merged) and DELIV C2a (row 61) is not merged.

Anchor refresh. No anchored engine or CLI file changed between the revision 7 bases (engine `2b8a47fbe`, CLI `d6b9e4c7`) and today's bases. The revision 7 header already listed the right lines for most of the cases below, but the tables still had the older lines. This extract uses the right lines:

| Where | Revision 7 table text | Now |
|---|---|---|
| A7 test comment | `CT:e2e/test_init_command.py:127` | `:121-122` |
| A8a gate location | `C:cli/gate/_layers.py:213-215` | `_schema_findings` at `:150-158`, called at `:179` and `:205`; the `.format` location is built at `:250` |
| A8b dead guards | `C:cli/run/_execute.py:308-310`, `C:cli/demo.py:300-302` | `_execute.py:407-408`; `demo.py:299-300` (`:301` is the write) |
| D5 `_report_kwargs` | `C:cli/run/_execute.py` ~342-368 | built at `:448-457`, forwarded at `:476` |
| A5 activation flag | `E:execution/_unified_slice.py:334-335` | `:345-346` |
| A5 route anchor (8b) | `E:execution/_unified_slice.py:359` | `:370` (the `except Exception`) |
| `write_targets` callers (8b) | `C:api.py:633`, `C:cli/tokenize.py:371`, `C:cli/demo.py:295` | `C:api.py:653`, `C:cli/tokenize.py:375`, `C:cli/demo.py:293` |
| DELIV keeps the old path | `plan/deliv` lines 455-460 | the C2a `run/_execute.py` bullet at lines 834-837 |

Two planner notes for review (sections 10 and 12): the CLI `cli/io/_targets.py` is 793 lines against the CLI module-size `LIMIT = 800`, so C-F1b's additions do not fit in that file (OQ-PF2); and engine PR 821 changes when the "Surface release" can ship, which C-F1a waits on (OQ-PF1).

PR 821 cross-check: PR 821 keeps E-S1a and E-S1b "from the batch plan ... first and unchanged" and has no E-F1, E-F2, C-F1a or C-F1b content. Its "D9" is `profile_document` (its own numbering); the batch plan's D9 (`E:quality/dp_budget.py` `__getattr__`) rides E-F1 as before. The 24zi emit-helper item (`_dispatch_sink` in `E:context.py`) rides E-S1b; PR 821's W3 moves only the root bindings of `emit_lineage`, `emit_step` and `emit_throughput_sample`, so the two do not conflict.

## 1. Pinned guarantee and non-goals

Guarantee. After this row:

- (a) no `text_mask` span is written back with its real value unless its strategy is `passthrough`, and no detector and strategy pair that the code cannot carry out compiles (shipped in E-F0, engine #617);
- (b) no failure listed in 24zi turns into a weaker output while the run reports success, and a new broad handler that swallows its exception under `src/` fails the `swallowed-broad-except` ratchet in either repo (section 5).

Non-goals:

- No new feature. Each item is a fix to existing behavior or a deletion.
- The broad catches in `E:execution/_chunked_fk_dtype_safety.py` stay. They fail closed (return False, which refuses the edge), and narrowing them safely would have to name `OSError` (`ZoneInfo("America")` raises `IsADirectoryError` on Python 3.10) and `AttributeError` (`pa.decimal32` is absent before pyarrow 18; the floor is `>=14`). Recorded as kept, not fixed.
- No platform change. The platform is parked on engine 0.18.0.
- Rows 24zj, 24zk and 24zl are not in this file. Two of their items ride 24zi slices because they share files: D9 (24zk) in E-F1, D5 (24zk) in C-F1a. The 24zi emit-helper item rides E-S1b (24zj surface lane).

## 2. Items

No 24zi item other than A1 (E-F0) and A4 (engine #596) is fixed on main.

| Item | Site (at base) | Defect | Reachable | V1 behavior | Slice |
|---|---|---|---|---|---|
| A1 (merged, engine #617) | `E:transforms/text_mask.py` `_mask_faker` | The inner `try` was unreachable; the reachable defect was the E-F0 leak. | Yes, through E-F0. | Shipped in E-F0. | E-F0 |
| A2 | `E:transforms/geo_generalize.py` `_build_state_map` (272-282; `except Exception` at 280, warning at 281, `return {}` at 282, called at 345) | A failed `load_table("us_zip5_city_state")` returns `{}` with a warning, so every state value is `""`. | Only on a broken install (the table ships in the wheel); reference #308 notes the effect is wrong masked output (over-suppression), not only a warning. | The load failure becomes a coded `ExecutionError` (`runtime.reference_table_unavailable`, declared beside `TRANSFORM_SOURCE_MISSING` in `E:reasons/runtime/_part2.py`), raised after the `except` closes; `decoy run` exits 3 through `exit_code_for` (a broken install is a runtime fault, not a config mistake). The zip5 table loads only when `state` is in the cascade, so a run that never asks for state never touches it. | E-F1 |
| A3 | `E:plan/_seed_envelope.py` (`:126`; import at `:73`) | `except _ProviderError: reg_caps = None`. | No. `check_unknown_provider` runs first at `E:plan/_compile.py:194`, and in the config-only checks at 523. | Catch deleted. | E-F1 |
| A4 (closed on main by engine #596) | `E:plan/checks/_generate_columns.py` `_expression_refs` (deleted) | `except Exception: return frozenset()`. | No. | Nothing left to do. | none |
| A5 | `E:execution/_unified_slice.py` (370-372) | `except Exception` logs `_REROUTE_LOG` (`:75`) and returns None, so the caller reruns the slice on pandas. A native bug becomes a slower correct run. | Yes, on any exception in the callees listed in section 3. Output does not change (the pandas oracle is correct). | Section 3. Owner question OQ-3. | E-F2 |
| A6 | `E:execution/physical/_compiler.py` `_post_scan_resident` (442-450) | `except Exception: return None` around `post_scan_resident_for(...)`, evidence only. The runtime calls the same function with no catch. | Only on an internal bug. | Catch deleted. | E-F1 |
| A7 | `C:cli/init.py` `_validate_scaffold` (308-325; `except Exception` at 322) | `try: import yaml; from decoy_engine.config import parse_pipeline_config except Exception: return`. Both are hard dependencies, so a broken install skips scaffold validation. | Only on a broken install. | Plain import with no `try`, kept inside `_validate_scaffold` (function-local, so AT-A7's call-time `sys.modules` patch exercises it); update the comment at `CT:e2e/test_init_command.py:121-122`. | C-F1a |
| A8a | `E:config/_targets.py:161-173` `duplicate_target_groups` and `E:config/_pipeline.py:490` `PipelineConfig._targets_distinct`; the old CLI skip is `C:cli/io/_targets.py:665-667` (`_file_targets`) | A `targets:` key that names no configured table is never refused; a source name alone is not a valid target key. `write_targets` skips it and the run exits 0 with no file. | Yes, from any config with a typo in a target key. | The engine config validator is the one refusal point. Beside `_targets_distinct`, it checks target keys against table names only, raises the new engine code `config.target_table_unknown`, and updates `duplicate_target_groups`'s docstring so it no longer says writers skip unknown keys. CLI run and validate both exit 1 before any source read: `decoy run` raises the code early through `early_schema_findings` over the named tuple `EARLY_SCHEMA_CODES` in `C:cli/gate/_layers.py` (today `shared_destination_findings`, `:162-182`, which raises early only for `TARGET_SHARED_DESTINATION`). The gate location is `targets.{table}`, not `targets.{table}.format` (schema findings come through `C:cli/gate/_layers.py:150-158`, called at `:179` and `:205`; `:250` adds `.format`). | E-F1; CLI repin and C-F1a acceptance |
| A8b | `C:cli/io/_targets.py` `write_targets` (`:670-688`, skip in `_file_targets` `:650-667`); DELIV C2a retains `_write_mask_outputs` for `C:cli/tokenize.py:375` and `C:api.py:653` until C4; `C:cli/demo.py:293` has a separate `_write_mask_outputs`; RUN-STREAM C1a adds `seal_result` | A declared file target whose table the engine did not produce is skipped (`table = outputs.get(table_name); if table is None: continue`) and the run exits 0. Engine #584 (LOADER-DROP) closed one cause; the skip still hides any other. | Yes, on any engine result that lacks a declared table. | `missing_target_tables` is the one predicate, over every declared target of any `type`. Both `seal_result` and `write_targets` call its raising wrapper `refuse_missing_targets` before any write, so the retained tokenize, API and demo paths refuse too. Tokenize also calls it before `token_vault.commit()`. Demo moves onto the shared check instead of owning a second rule. New CLI code `target.table_missing` on `TargetTableMissingError`, exit 3 through `exit_code_for`. Section 4. Also delete the dead `if not isinstance(outputs, dict)` guards at `C:cli/run/_execute.py:407-408` (in C-F1a, the `_execute.py` lane) and `C:cli/demo.py:299-300` (here); `outputs` is always a dict. | C-F1b |
| A9 | `C:cli/run/_render.py` `_next_hint_for_run` (53-61), used at 186 | Reads `raw_cfg["output"]["path"]`, a key the V2 schema does not have, inside `try/except: pass`. Always None. | Dead code. | Deleted; the caller drops the keyword. `_render.py` is held by RESULT (row 62) inside F29 C1 (row 66): this hunk rides with that holder if it is open when C-F1a builds. | C-F1a |
| Emit helpers | `E:context.py` `emit_step`, `emit_lineage`, `emit_fidelity`, `emit_quarantine`, `emit_throughput_sample` | Five copies of `getattr` probing plus `except Exception: pass`; `emit_step` also retries without `node_id` on `TypeError` (D12). No failure is counted. | The catch is a deliberate observation boundary: a logger that raises must not fail a run. The five copies and the `TypeError` retry are the defect. | One private `_dispatch_sink` in `E:context.py` owns the probe and the catch; it logs the exception class name (value-free) at DEBUG on the engine logger and counts nothing. The `TypeError` retry goes. Planned and built in the source plan's E-S1b (24zj lane); listed here so row 24zi is complete. | E-S1b |

Items from other rows that ride these slices (unchanged from the source plan section 4):

- D9 (24zk): `E:quality/dp_budget.py` 499-520, a module `__getattr__` (`:507`) that re-exports `OpenDpReleaseSession`, plus `if TYPE_CHECKING:` at `:503`. Delete. Update the docstrings that name the old path (`E:quality/dp.py:11`, `E:quality/dp_session.py:16`). Slice E-F1.
- D5 (24zk): `C:cli/run/_execute.py`, `_report_kwargs` (`:448-457`, forwarded at `:476`) is left out "so the default call shape stays valid on an older engine". Pass the keywords. Slice C-F1a (same hot file as A9).

Failure modes:

- A5: a native exception that rerouted today now fails the run. Section 3 has the flight.
- A8a: a config with a typo in a target key that exits 0 today now exits 1 at config time. This is the intended change.
- A8b: a sink-route table the engine streamed to the sink is not in `outputs`; the check counts it as produced (section 4).
- A8b in tokenize: a refusal after `token_vault.commit()` would leave committed mappings for output that was never written. The check runs before the commit, so the `finally` discards the uncommitted vault (`C:cli/tokenize.py:414-418`).
- A2: a working install sees no change, so the test injects a loader failure.
- A3, A6: unreachable on a correct build; deleting the catch can only surface an internal bug as a raise.
- A7: a broken install now raises `ImportError` from `decoy init` instead of writing an unvalidated scaffold.

## 3. A5 detail (slice E-F2)

Callees inside the `try` (`E:execution/_unified_slice.py`, `try` at 192, `except Exception` at 370) and the verdict for each:

| Callee | On exception |
|---|---|
| `build_live_physical_plan_inputs` (`E:execution/physical/_live_inputs.py:47`) | propagate. The module has no `raise`; anything that escapes comes from a callee the oracle also runs |
| `compile_physical_plan` (`E:execution/physical/_compiler.py:387`) | propagate. Its docstring (`:388-390`) says it raises the same exception a live `run_pipeline` call would raise. Its raises are `require_resident_fit`'s capacity error (`E:execution/pipeline/_resident_fit.py:153`) and `AssertionError` (`_compiler.py:272`, `:339`, `:381`). Rerouting an oracle-identical refusal only runs the oracle to the same error, so it propagates now |
| `_admission.resident_contract_admission` | propagate (admission declines are return values; the resident decline returns None inside the `try` at `:227-236`) |
| `build_unified_slice_activation` | propagate |
| `ShadowContext.from_key_provider` | propagate |
| `capture_shadow_snapshot`, `compute_when_masks` | propagate |
| `ShadowCoordinator(...).run` | The `FAKER_POOL_NON_STRING_OUTPUT` reroute arm at `:252-265` (code check at `:258`, return at `:265`) is unchanged; any other `ShadowDifference` raises `UnifiedSliceInvariantError`; anything else propagates |
| `assemble_node_evidence`, `deterministic_faker_pin_columns`, `reconstruct_source_shaped_output` | propagate |
| `_pipeline_finalize.stamp_execution_metrics`, `_pipeline_route_exec.execution_telemetry` | propagate |
| `_pipeline_finalize.finalize_validators_and_quarantine` (`:325`) | propagate. Only the configured validator and quarantine branch is unreachable on main: admission declines any validators or quarantine config before the `try` (AT-A5b pins the decline). An admitted run still calls the finalizer at `:325`; the boundary test injects there (`ET:physical/test_unified_slice_exception_boundary.py:171-174`) |
| `_typed_warnings`, `_typed_row_errors` and `ExecutionResult` construction | propagate |
| `PoolBuildFailed` handler | unchanged |

The rule is one rule:

- `_REROUTABLE` in `_unified_slice.py` is the only thing that reroutes. Its members:
  1. `pyarrow.ArrowInvalid` and `pyarrow.ArrowTypeError`, by exact class. Decided: reroute. The native lane converts through Arrow, and Arrow refuses data that the pandas oracle accepts (for example a mixed-type object column). The oracle output is correct, so failing those runs would be a function break. Both classes subclass `ValueError` and `TypeError`, so the tuple names them exactly and a plain `ValueError` or `TypeError` is not caught;
  2. `MemoryError`. Decided: reroute. The unified lane holds the shadow snapshot and the reconstructed output at once, so its peak is above the oracle's, and today's reroute is what lets those runs finish. Failing them would be a function break.
- Everything else propagates. Reference #308 lists `ValueError`, `KeyError` and `TypeError` as classes that reach the handler today; each one found by the census is a lane bug. E-F2 fixes it at the source or stops and reports. It is never added to `_REROUTABLE`.
- No coded "slice not eligible" raise exists in the two plan callees at the base (enumerated above), so the source plan's coded-decline group is deleted. Oracle-identical refusals (a `ConfigError`, `PlanCompileError` or capacity error that `run_pipeline` raises for the same snapshot) propagate unchanged. If the census finds a coded raise that the oracle does not raise for the same config, that is a lane bug, handled as below; no code-checking arm is added.
- The reroute log line stays value-free: it names the class only.

Error parity (AT-A5b). Once the catch is gone, a user error that the lane hits first reaches the caller as the lane's own type. The census therefore records, for every AT-A5b user-error cell, the raw exception type and reason code on the unified lane beside the same pair on the oracle (`unified_slice_enabled=False`). Each mismatch is fixed at the lane's raise site by building the error with the constructor the oracle uses. The pattern is `E:execution/_errors.py`, whose `text_mask_unsupported_pair_error` already keeps "the code and message identical on the handler, the native chunked route and the out-of-core route". The fix is never a translation table at the `_unified_slice.py` boundary. If the fixes need production files beyond the two E-F2 files, the builder lists them and stops for a plan re-scope with the new file budget (the 10-file cap holds). A sentry cannot enforce this; AT-A5b is the guard.

Census (in E-F2, before the narrowing commit, recorded in the PR evidence). A temporary recording handler writes `type(exc).__qualname__`, the raising module and, if present, the reason code for every exception that reaches the `except`. It runs over `ET:physical/`, `ET:parity/`, `ET:native/`, `ET:unit/execution/`, `ET:integration/` (golden), the compat corpus suite, the testflight acceptance suite, and the flight below. Every class found is placed in one of the two `_REROUTABLE` groups or named as a lane bug. The census also holds the AT-A5b parity table (lane type and code beside oracle type and code, per cell). A census with zero unified-slice activations is void.

Instrument for OQ-3 (no production change): before E-F2 merges, the test flight (`scripts/test_flight.py`, golden corpus plus the prodsim set) runs on engine main under a wrapper that attaches a `logging.Handler` to logger `decoy_engine.execution._unified_slice` and counts records whose message starts with `unified_slice_unexpected_exception_reroute`, grouped by `exc_type`. The flight counts only if (1) `decoy_engine.native_companion_status()` reports the companion loaded and (2) at least one run has `quality_metrics["unified_slice_activation"]["activated"] is True` (`_unified_slice.py:345-346`). A flight with zero activations is void, not clean. The wrapper and the counts go into the E-F2 PR evidence.

E-F2 also narrows the A4-adjacent `except Exception: continue` at `E:plan/_checks.py:637` to `decoy_engine.errors.ValidationError` (`E:errors.py:77`), the class `compile_expr` raises, not pydantic's `ValidationError`. E-F1 has no file budget for it. `compile_expr` (`E:expressions/_lark_parser.py:79`) imports that class (`:43`) and raises it at `:118`, `:135`, `:156` (the lark `ParseError`, `UnexpectedCharacters`, `UnexpectedToken` and `UnexpectedEOF` arm at `:143-147`), `:171` (`RecursionError` at `:167`) and `:185` (dunder identifier). After parsing it runs `_validate_string_escapes` (called `:193`, defined `:225`), which raises the same class at `:240`, and `_rewrite_if_calls` (`:211`), which has no `raise`. AT-CHK proves that set: anything else `compile_expr` raises now propagates from plan compile instead of being skipped.

## 4. A8b detail and plan amendments (slice C-F1b)

Placement. DELIV C2a (row 61, engine `plan/deliv` `docs/plans/2026-11-12-deliv.md`, the C2a `run/_execute.py` bullet at lines 834-837) turns the run route into a `DeliverySink.write_table` loop over `result.outputs`, but explicitly keeps `_write_mask_outputs` as the old non-sink path for `cli/tokenize.py` and `api.py` until C4. `cli/demo.py:293-301` owns another wrapper over `write_targets`. RUN-STREAM C1a (row 63a, CLI `plan/run-stream-r6-5` `docs/plans/2026-11-08-run-stream.md`, lines 790-798) adds `seal_result(outputs)` for run routes. It is not the only post-engine writer.

The check is one function, `missing_target_tables(config_dict, outputs, engine_written) -> list[str]`: the declared targets whose table is in neither `outputs` nor the set of tables the engine wrote through the sink. "Declared" means every key of `targets:`, whatever its `type`. It is not limited to the `type: file` entries that `_file_targets` (`C:cli/io/_targets.py:650-667`) selects, because once DELIV C2a delivers through `DeliverySink.write_table` over `result.outputs`, a missing S3 or GCS table would otherwise be skipped without a word. On main a cloud target is still refused before the run (`C:cli/run/_execute.py:348`), so the cloud branch is first reachable when DELIV C2a lands, which C-F1b already waits on. A thin `refuse_missing_targets(config_dict, outputs, engine_written)` beside it raises `TargetTableMissingError` when the list is not empty. It is the only raise site, so the message is built once.

The error and its code:

- `class TargetTableMissingError(Exception)` with a `code` attribute and a fixed message that names the table names only. It follows `LayoutError` (`C:cli/io/_layout_errors.py:23-31`). It is not a `ValueError` subclass, so no existing usage arm catches it by accident (`TargetFormatError` is a `ValueError`, `C:cli/io/_targets.py:78`).
- Code constant `TARGET_TABLE_MISSING = "target.table_missing"` in `C:cli/io/_target_presence.py`, beside its owner. The CLI keeps codes beside the owning module (`C:cli/io/_targets.py:57-58` `target.csv_*`, `C:cli/io/_integrity_report.py:38`). It has no reason registry module and no `io.` namespace, so the source plan's `io.target_table_missing` is renamed under the existing `target.` prefix.
- Exit: one explicit row in `exit_code_for` (`C:cli/exit_codes.py:195`), `isinstance(exc, TargetTableMissingError) -> EXIT_RUNTIME`, imported lazily like the other CLI types there. Keep the explicit runtime row after the usage-type check to document the exit contract. The default also returns 3. A matching row goes in the recorded table `CT:unit/test_exit_code_for.py`. `decoy run` (through `run_category_for`, `C:cli/run/_errors.py:176`) and `decoy demo` (`C:cli/demo.py:361-362`) already take their exit from the map.
- Run registers `TargetTableMissingError` in `_cli_refusal_types()` (`C:cli/run/_errors.py:76-83`) as a refusal with authored, table-name-only text. In the existing envelope code selection (`:298-310`), promote a registered CLI refusal's `getattr(exc, "code", None)` through the existing `is_reason_code` check. Preserve post-scan and capacity precedence. Demo handles this refusal before its generic text-only envelope (`C:cli/demo.py:362-380`) using the existing `emit_error` with the authored text and `code=exc.code`, then exits through the map.
- Extend `CT:sentry/run/test_one_run_reason.py` with `test_coded_cli_exceptions_are_registered`. Discover exception classes defined throughout `decoy.cli` independently of the tuple, including class, instance and inherited `code` attributes. Assert each is covered by a type in `_cli_refusal_types()`. Register existing uncovered families there as well. Preserve the fixed-text boundary in the same module: share the existing trusted group plus the new table-name-only refusal with `_fixed_text_types()`. Registration solely for carrying a code must never authorize rendering free-form text. Remove `TargetTableMissingError` from the refusal registry: the sentry must report the missing class.

Callers:

- `seal_result` calls `refuse_missing_targets` first, before any write.
- `write_targets` calls it first with an empty `engine_written` set, so API and the old run path refuse too. Demo deletes its local decision and reaches the same check through `write_targets`.
- Tokenize calls `refuse_missing_targets` right after `run_pipeline` returns and before `token_vault.commit()` (`C:cli/tokenize.py:373`). Today the vault is committed before `_write_mask_outputs` (`:375`), so a refusal raised from `write_targets` would leave committed mappings for output that was never written (catalog class 2). The `write_targets` call stays as the choke point; on this path it finds nothing missing.
- Tokenize gets its own arm, `except TargetTableMissingError as exc: _emit_error(<message>, code=exc.code); raise typer.Exit(code=exit_code_for(exc))`, placed before the generic `except Exception` (`:396`). Without it that arm would print "unexpected TargetTableMissingError ... Re-run" and drop the code.
- `C:api.py:653` lets the error reach the Python caller with its `code`. The API has no exit code.

The one predicate and the writer choke points are guarded together (section 7). The source plan places the function and error in `C:cli/io/_targets.py`; see OQ-PF2 for the size problem with that file.

Amendment notes for the two plans (the orchestrator applies them to those plan files when this plan passes the gate; they are written here so the change is reviewed once):

- RUN-STREAM `plan/run-stream-r6-5`, `2026-11-08-run-stream.md`, the `seal_result` bullet at lines 790-793: replace "A target key that names no output table expects nothing, as in today's `write_targets` (`:487-489`) and DELIV's file-target set" with "Every target key names a config table (PROP A8a refuses others at config time). A declared file target whose table is neither in `outputs` nor engine-written is refused by `missing_target_tables` with `target.table_missing`, exit 3, before any write (PROP A8b)."
- RUN-STREAM line 1160, AT-C1e: replace "a target key naming no output table (skipped, not refused)" with "a target key naming no config table (refused by PROP A8a) and a declared target whose table is missing from both resident outputs and the engine-written set (refused by PROP A8b before sealing)." Align the revision table at lines 135 and 197 with the same rule.
- DELIV `2026-11-12-deliv.md`, the C2a `run/_execute.py` bullet (lines 834-837 at `plan/deliv`): add "`write_targets` calls PROP A8b's shared `missing_target_tables` check before its first write. The retained tokenize and API callers therefore refuse until C4; RUN-STREAM's `seal_result` calls the same check for sink-aware run routes. The check covers every declared target type, so a cloud target whose table is missing is refused, not skipped."

- Both plans (DELIV C3 and any RUN-STREAM slice): add "A deliberate new broad `except Exception` boundary (for example DELIV C3's best-effort handler per chunked table) is counted by the PROP `swallowed-broad-except` ratchet. The slice that adds it lands an `approved_growth` row for its exact baseline key in `scripts/dev/sentry_registry.toml`, with a dated owner decision (`owner YYYY-MM-DD <reason>`), in the same PR. The baseline entry gets the matching reason and `max`. `approved_growth` admits a new key only, so the boundary goes in a file with no counted site, or the slice narrows an existing site in its file (PROP plan section 5)."

Engine routes and the every-declared-table guarantee. A8b is safe only if every route returns or streams each config table. The routes, from `E:execution/`:

| Route | How tables reach the CLI |
|---|---|
| full frame (`_pipeline_full_frame.py`) | `outputs` dict, every config table |
| sequential (`_sequential.py`) | `outputs` dict |
| mixed (`_pipeline_mixed_route.py`, `_mixed_static.py`) | `outputs` dict |
| unified slice (`_unified_slice.py`) | `outputs` dict, or rerouted to full frame |
| out-of-core and chunked with a sink (`out_of_core/`, `_chunked_output_sink.py`) | written through the sink (engine-written set) |
| isolated child (`_isolated_reason.py` and the governor) | `outputs` from the child, or a terminal outcome |
| generation only | `outputs` dict |

This table is a claim to prove, not a finding. AT-A8b runs one two-table config per route and asserts each declared table is in `outputs` or the engine-written set. A route that drops a table is a finding for that route, fixed at the route; the check is never relaxed to pass it.

## 5. Class guard: `swallowed-broad-except` (engine in E-F1, CLI in C-G2)

Row 24zi fixes nine sites by hand. The class is "a broad handler that keeps going", and nothing stops the tenth. Under the standing "sentry over prose" rule, each repo gets one shrink-only ratchet over `src/`.

What counts as one site:

- An `except` handler whose type is bare (`except:`), `Exception` or `BaseException` (as a name or an attribute such as `builtins.Exception`), or a tuple that holds one of them, and whose body holds no `raise` statement. A `raise` inside a nested `def`, `lambda` or `class` in the handler does not count as a re-raise.
- A `with contextlib.suppress(...)` or `with suppress(...)` whose arguments include `Exception` or `BaseException`.

What does not count:

- A handler with any `raise` in its own body (bare `raise`, `raise X from exc`, or a raise under an `if`). A conditional raise is accepted as handled; that under-count is known and accepted, since the realistic quiet fallback has no raise at all.
- A handler that saves the error and re-raises after the block. All three must hold: (1) the handler binds `as exc`; (2) inside that handler's own body (nested `def`, `lambda` and `class` excluded) an assignment stores an expression that holds `exc` into a local name; (3) the same function scope has a `raise` whose exception or `from` cause names that local, and that `raise` starts lexically after the end of the complete `try` statement (its `end_lineno`, so after every handler, `else` and `finally`), not inside a nested `def` or `class`. A raise before the `try`, or inside it, does not count. Engine `8796ef691` has about 26 such handlers. They are correct and stay uncounted; the exact number is in the E-F1 evidence under the tightened rule.
- Narrow handlers (`except ValueError`, `except OSError`, `suppress(FileNotFoundError)`).
- Anything under `tests/`, `scripts/` or `docs/`.

Count at the base (planning scan, `ast` over `src/` at the revision 5 bases, deduplicated): engine about 144 sites in 77 files (one `suppress`); CLI about 53 sites in 27 files (four `suppress`). The exact numbers are what the guard's `--write` mode records at the slice head.

Mechanism, reusing the existing ratchet:

- One predicate module, engine `tests/sentry/defects/_swallowed_except.py`: `swallowed_sites(tree: ast.Module) -> list[Site]`, standard library `ast` only. The CLI vendors it byte for byte and pins it in `ci/vendored.toml`, as it already does for `tests/sentry/layout/_layout.py`. The rule is written once.
- One sentry per repo, `tests/sentry/defects/test_swallowed_broad_except.py`. It counts sites per file and compares with the baseline `tests/sentry/baselines/swallowed-broad-except.json`, shape `{"sentry_id", "created_in", "entries": {"<repo path>": {"reason", "max"}}}`, the shape of the CLI `retired-name-pending.json`. One row in `scripts/dev/sentry_registry.toml` per repo. It is a JSON baseline from its first commit.
- The sentry fails when a file's count exceeds its `max`, when a file with sites has no entry, and when a count falls below its `max` (the message says "lower max to N"), so every fix shrinks the baseline in the same PR and no headroom is left for a new site.
- `scripts/dev/ratchet_check.py` already refuses a new key and a raised `max` against the merge base. A new file with a swallowing handler is therefore refused twice: by the sentry and by the ratchet.
- Each entry carries a reason of at least 15 characters (`MIN_REASON`). The builder assigns one of these per file, from reading the handlers:
  - "observation boundary: a telemetry or logger failure must not fail the run" (the engine `pyproject.toml` S110 and S112 ignores give the same reason);
  - "fail closed: the handler returns the refusing value";
  - "best-effort cleanup after the primary error is already raised or recorded";
  - "reports a broken install; this command's job is to describe the failure" (for example `C:distribution/selfcheck.py`);
  - "unclassified catch-all with no named failure; open 24zi follow-up". This is the honest label for any handler the builder cannot place. The build report counts these rows.
- Placement in time: the engine baseline is written at the E-F1 head, after A2 and A6 have deleted their catches, so those are never baselined (A4 is already gone on main). E-F2 (A5), E-S1b (emit helpers: five handlers in `context.py` become one in `_dispatch_sink`) and any later 24zi fix lower the `max`. The CLI baseline is written at the C-G2 head. If C-F1a merges first it skips its ratchet step and C-G2 writes the baseline without the A7 and A9 sites; otherwise C-F1a lowers it afterwards.

A module split that moves a counted handler into a new file adds a key, which the ratchet refuses. The split narrows the handler or adds the `raise`; the baseline is never grown.

Deliberate new boundaries. Some planned work adds a broad handler on purpose, for example DELIV C3's best-effort `except Exception` per chunked table (deliv plan, just after line 837). "No headroom" does not block it, and no second exemption mechanism is added. The only path is the ratchet's existing `approved_growth` route: `parse_approvals` in `tests/sentry/_ratchet.py` (engine `:126-150`; the CLI copy documents it at `:11` and reads it at `:139`) accepts an added key only when `scripts/dev/sentry_registry.toml` lists an `approved_growth` row for that exact key with a dated owner decision `owner YYYY-MM-DD <reason>`. The slice that adds the boundary lands, in the same PR, the baseline entry (reason and `max`) and the `approved_growth` row. Builders do not write owner decisions, so the slice asks for one through [[OWNER-QUESTIONS]] before it merges. The section 4 amendment notes tell DELIV and RUN-STREAM this. `approved_growth` admits an added key only; a raised `max` on an existing key is refused with no approval path (engine `_ratchet.py:486-490`). So a boundary that would land in a file that already has counted sites either narrows one of that file's existing sites in the same PR, or sits in a file of its own and takes the approved new-key route.

Fail-before: the seeded self-test cells below have no scanner to run on main, and the tree test fails on main with no baseline (about 144 engine and 53 CLI findings).

## 6. Established solutions

- The R2 slices here (E-F1, E-F2, C-F1a, C-F1b) add no parser, scheduler, protocol or method. They delete catches, add one config validation beside an existing validator (`PipelineConfig._targets_distinct`), add one post-engine predicate, and narrow one handler to a named tuple. The patterns followed are in the codebase: `duplicate_target_groups` and `TARGET_SHARED_DESTINATION` for A8a, the frozen-surface update steps in `docs/frozen-surfaces.md` for D9.
- Narrowing a broad catch to named classes is the Python standard practice behind ruff `BLE001` and pylint `W0718` (catch what you can handle, let the rest propagate). A5's `_REROUTABLE` tuple is that practice with three named groups.
- Swallowed-broad-except guard. Searched 2026-11-17: "ruff BLE001 blind-except", "pylint broad-exception-caught W0718", "ruff S110 try-except-pass baseline". The published rules are ruff `BLE001` (blind except), `E722` (bare except), `S110`/`S112` (try-except-pass/continue) and pylint `W0718`/`W0719`. The predicate follows `BLE001`: a broad handler that re-raises is not flagged. It differs in two ways, on purpose. `BLE001` also exempts a handler that logs with `exc_info`, and a logged-and-continued failure is exactly the 24zi class. And `BLE001`'s only baseline is inline `# noqa`, which a contributor can add without review; the project's `_ratchet.py` baseline is shrink-only against the merge base. The engine already ignores `S110`/`S112` globally (`pyproject.toml`, "telemetry paths intentionally swallow"), so turning them on would need hundreds of `noqa` lines. The custom code is one `ast` predicate (about 80 lines) plus a sentry in the existing ratchet framework.
- Sameness questions. (1) Does this do what another module already does differently? A8a adds no second target validator: the CLI consumes the engine refusal and adds none. A8b has one predicate shared by `seal_result`, `write_targets` and (through `write_targets`) demo, replacing demo's own decision. The ratchet predicate is written once in the engine and vendored by pin. (2) Could it live in one central place? Yes, and it does: unknown target keys are owned only by `PipelineConfig._targets_distinct`; missing tables only by `missing_target_tables`; the reroute set only by `_REROUTABLE`.

## 7. Choke points and guard mutations

| Class | Choke point | Guard test | Mutation that must turn the guard red |
|---|---|---|---|
| Unknown target key (A8a) | `PipelineConfig._targets_distinct`, using the target-name helper beside `duplicate_target_groups` in `E:config/_targets.py`. CLI early refusal: the named tuple `EARLY_SCHEMA_CODES` read by the one function `early_schema_findings` in `C:cli/gate/_layers.py` | Engine config tests plus `CT:unit/cli_fmt/test_target_table_unknown.py`; the CLI test asserts gate location `targets.custmers` and the `--duckdb-source` cell (AT-A8a) | Drop the validator call: the typo config exits 0. Drop `TARGET_TABLE_UNKNOWN` from `EARLY_SCHEMA_CODES`: the `--duckdb-source` cell sees the source read before the refusal. |
| Declared table not produced (A8b) | `missing_target_tables` (raised only through `refuse_missing_targets`), called first in both `seal_result` and `write_targets`; demo reaches it through `write_targets`; tokenize also calls it before `token_vault.commit()`. Exit: the `TargetTableMissingError` row in `exit_code_for` | `CT:unit/cli_fmt/test_write_targets_missing_table.py` plus tokenize, API, demo and cloud caller cells; `CT:unit/test_exit_code_for.py` row | Skip the call in either writer: that writer's cell sees exit 0 and a written file. Move the tokenize call after `token_vault.commit()`: the tokenize cell finds committed mappings. Add `TargetTableMissingError` to `usage_error_types()`: the recorded row gets exit 1 instead of 3. Restrict the predicate to `type: file`: the cloud cell exits 0. |
| Coded CLI refusals (A8b) | `_cli_refusal_types()` owns refusal membership and the run envelope reads the code from that family | `CT:sentry/run/test_one_run_reason.py::test_coded_cli_exceptions_are_registered` and AT-A8b | Remove `TargetTableMissingError` from the registry: the sentry reports it. Drop CLI code promotion: the run JSON cell loses its code. |
| Native-lane reroute (A5) | the `except` in `E:execution/_unified_slice.py` (`:370`) | `ET:physical/test_unified_slice_exception_boundary.py`, an intended rewrite of the current reroute assertion at `:213` | Widen the catch back to `Exception`: an injected `RuntimeError` reroutes. |
| Swallowing broad handlers (24zi class, section 5) | the per-file `max` in `tests/sentry/baselines/swallowed-broad-except.json` (both repos), enforced by the sentry and by `scripts/dev/ratchet_check.py` | `tests/sentry/defects/test_swallowed_broad_except.py` (both repos) over the one predicate `tests/sentry/defects/_swallowed_except.py` (engine source, CLI vendored copy) | Delete the save-and-re-raise exclusion from the predicate: the seeded `saved_then_raised` cell counts 1 and goes red, and the engine tree count exceeds the baseline by the save-and-re-raise handlers. Ordering mutation: drop the "raise starts after the try's `end_lineno`" check; the seeded `raise_before_try` cell counts 0 instead of 1 and goes red. Second mutation: drop the `suppress` branch; the seeded `suppress(Exception)` cell goes red. Tree mutation: add `except Exception: pass` to a `src/` file with no entry; the sentry and `ratchet_check` both go red. |
| Observation sinks (emit helpers, rides E-S1b) | one private `_dispatch_sink` in `E:context.py` | `ET:unit/test_context_emit_dispatch.py` | Delete the `except` in the helper: a raising sink fails the run. |

Each walk is shown to see a seeded violation in a scratch copy before its count is trusted.

## 8. Acceptance tests (fail before, pass after)

Each test is written first and must fail on the base commit named in the header, except where the row says it pins a no-regression fact.

| Id | Test | Fails before because |
|---|---|---|
| AT-A2 | Monkeypatch `load_table` to raise `FileNotFoundError`: `geo_generalize` with the state fallback raises `ExecutionError` with code `runtime.reference_table_unavailable`; `__cause__` and `__context__` are None; the message names the reference table only. Through the CLI, `decoy run` on that config exits 3 (`exit_code_for`). A cascade without `state` never calls the loader (the lazy-load half of the A2 row). | Returns `""` states with a warning, exit 0. |
| AT-A3, A6 | No behavior test (unreachable). An ordering test, `ET:unit/plan/test_compile_check_order.py`, pins that `check_unknown_provider` runs before `_build_seed_envelope` (A4 closed on main). | Passes before; it pins why each catch is dead. |
| AT-A5 | Inject a `RuntimeError` into `reconstruct_source_shaped_output`: `run_pipeline` raises it, and no `_REROUTE_LOG` record is emitted. | Reroutes and returns success. |
| AT-A5c | Inject, one cell each: `pyarrow.ArrowInvalid`, `pyarrow.ArrowTypeError` and `MemoryError`: each reroutes, the run succeeds, and the log names the class. A plain `ValueError` and `TypeError` propagate. An oracle-identical refusal from `compile_physical_plan` (a config `require_resident_fit` refuses) propagates with the same type and code as `unified_slice_enabled=False`, and no `_REROUTE_LOG` record is emitted. Mutation: drop `MemoryError` from `_REROUTABLE`; its cell fails the run. Second mutation: replace the Arrow classes with `ValueError`; the plain-`ValueError` cell reroutes and goes red. | Fail-before only for the `ValueError` and `TypeError` cells (they reroute today); the reroute cells pin today's behavior. |
| AT-A5b | In `ET:physical/test_unified_slice_exception_boundary.py`, error parity covers FPE sub-floor with no `sub_floor_span`, checksum failure, a `when:` expression error, the E-F0 `_mask_span` `ConfigError`, and provider failure. A separate pin configures a validator: the slice declines at admission and the oracle raises the validator error (the existing `test_admission_declines_validators_so_finalize_write_branch_is_unreachable` at `:322` and its quarantine twin at `:333`). For each, unified-slice on and `unified_slice_enabled=False` raise the same raw exception type, reason code and CLI exit code; the E-F0 execution cell matches the oracle's wrapped `StrategyError`, exit 3, rather than exposing the direct helper's `ConfigError`. The census parity table (section 3) is the input: each cell whose lane pair differs is fixed at the lane's raise site through the oracle's constructor before this test can pass. | On base the lane catches and reroutes, so the pandas rerun raises; the rewrite pins that removing the catch preserves the oracle boundary rather than exposing a lower-level type. |
| AT-A7 | Set `sys.modules["decoy_engine.config"] = None` at call time (so the function-local import raises `ImportError`) and call `_validate_scaffold`: the `ImportError` propagates. A source check pins that the import is inside the function, since a module-level import would bypass the patch. | Returns silently. |
| AT-A8a | Engine config with a `targets:` key `custmers` and a source of that name but no table: `PipelineConfig` refuses it with `config.target_table_unknown`. Through the repinned CLI, `decoy run` and `decoy validate` exit 1 before any source read and locate the gate finding at `targets.custmers`, not `.format`. A `decoy run --duckdb-source` cell refuses with `config.target_table_unknown` before the DuckDB stage reads any source (a spy on the source reader sees no call). `decoy compile --explain` refuses with the same code (`C:cli/compile_explain.py:186-188`). The target directory holds no new file (class row 2). | Exits 0, no file; under `--duckdb-source` the source is read before any refusal. |
| AT-A8b | Route matrix (section 4): for each run route, a two-table config, then the engine result with one table removed; `seal_result` raises `TargetTableMissingError` with code `target.table_missing`, `decoy run` exits 3, and neither file is written. Caller cells: `decoy tokenize` exits 3, prints the code, writes neither file and leaves no committed vault mappings (the vault file is absent or holds none from this run); `decoy.api` raises `TargetTableMissingError` with `code == "target.table_missing"` to the Python caller; `decoy demo` exits 3. For both run and demo, parse the `--json` envelope and assert `code == "target.table_missing"` and the missing table name in `error`. In text mode assert exit 3 and the missing table name in the error line. Check both modes for absence of the sample-row marker. Cloud cell (lands with C-F1b, after DELIV C2a): a declared S3 or GCS target (a fake `DeliverySink`) whose table is missing is refused with the same code and exit before any delivery. A chunked run whose tables were engine-written still exits 0. `__cause__` and `__context__` are None. A marker value from a sample row is absent from the error. | Each old writer skips the missing table, writes the other file and exits 0; tokenize commits the vault first. |
| AT-CHK (E-F2) | `ET:unit/plan/test_checks_derived_expr_narrowing.py`: malformed expressions that hit each `compile_expr` raise site (a parse error, a dunder identifier, a bad string escape, nesting deep enough for `RecursionError`) are skipped by the plan check as today (no `derived_missing_column_ref` double report). A monkeypatched `compile_expr` that raises `RuntimeError` now propagates from plan compile. Mutation: narrow to pydantic's `ValidationError`; the malformed cells raise and go red. | The `RuntimeError` cell fails before (the broad catch skips it); the malformed cells pin today's behavior. |
| AT-A9 | The run summary for a golden config is unchanged after the deletion. | Passes before; pins no regression. |
| AT-D5 (added in this extract; revision 7 names no D5 test) | With report flags off, `run_pipeline` receives the four report keywords with their defaults; with them on, the same keywords with the flag values; the run summary is unchanged. | Passes before for the "on" cell; the "off" cell fails because the keywords are left out. |
| AT-D9 (added in this extract; revision 7 covers D9 only through the frozen-surface map) | `from decoy_engine.quality.dp_budget import OpenDpReleaseSession` raises `ImportError`; `from decoy_engine.quality.dp_session import OpenDpReleaseSession` works; `docs/frozen-surfaces.md` and the release notes name the removed path. | The old path resolves through `__getattr__`. |
| AT-SBE | `test_swallowed_broad_except.py` seeded cells, each a parsed snippet with its expected count: bare `except: pass` (1); `except Exception: log(...)` (1); `except (ValueError, Exception): return None` (1); `except BaseException: continue` (1); `with contextlib.suppress(Exception)` (1); `with suppress(OSError)` (0); `except Exception as e: raise Wrapped() from e` (0); `except Exception: if bad: raise` (0, the accepted conditional case); `except Exception as e: err = e` then `raise err` after the `try` in the same function (0); `except Exception as e: err = e` with no later raise (1); `except Exception:` whose only `raise` sits in a nested `def` (1); `except ValueError: pass` (0); ordering cells: `except Exception as e: err = e` with `raise err` after the whole `try` (after its `finally`) (0), and the same handler with `raise err` placed before the `try` in the same function (1); `err` assigned outside the handler and raised after the `try` (1). The tree cell: every `src/` file's count equals its `max`. | No predicate or baseline exists; on main the tree cell has about 144 engine and 53 CLI unbaselined sites. |
| AT-EMIT (rides E-S1b) | `ET:unit/test_context_emit_dispatch.py`: a sink method that raises is swallowed and `caplog` holds one DEBUG record naming the class; a sink `step()` whose body raises `TypeError` is called once, not retried (D12). Mutation: restore the `TypeError` retry; the call count is 2 and the cell goes red. | Today `emit_step` retries on `TypeError` and logs nothing. |

## 8a. Class table (recurring defect classes)

| # | Class | How this row handles it | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | All new refusals (A2, A8a, A8b) name the table, target key, reference table or path only. The A5 reroute log names the class and the code, never a value. | AT-A8a, AT-A8b (marker absent from the error), AT-A5c (log record content). | Format a sample row into the A8b message: its marker check fails. |
| 2 | Cleanup missing on an exit path | A8a refuses before any read, including under `--duckdb-source`. A8b refuses before the first write, so no staged file is left. In tokenize it refuses before `token_vault.commit()`, so the `finally` discards the uncommitted vault. | AT-A8a and AT-A8b assert the target directory holds no new file; the tokenize cell asserts no committed mappings. | Move the A8b check after the first write: one file remains. Move the tokenize call after the commit: mappings remain. |
| 3 | State machine and concurrency | N/A: no state or thread is added. The emit dispatch helper keeps today's swallow rule; `seal_result`'s state machine belongs to RUN-STREAM C1a, and A8b only adds a check before its first write. | | |
| 4 | Route parity and silent fallback | The row's main class. A5 removes a silent route switch. A8b is proved per engine route and per retained CLI writer. A8a refuses at config time, before route choice, so every route sees the same refusal. The `swallowed-broad-except` ratchet (section 5) stops a new quiet fallback in either repo by construction. | AT-A5, AT-A5b, AT-A5c; AT-A8a; AT-A8b route and writer matrix; AT-SBE. | Widen the A5 catch: AT-A5 fails. Skip the predicate in `write_targets`: the API cell of AT-A8b fails. Drop the save-and-re-raise exclusion: AT-SBE fails. |
| 5 | Referential integrity | N/A: no key, FK or join behavior changes. The FK dtype catches are kept (section 1). | | |
| 6 | Untrusted producer | The config is the untrusted input for A8a; it is validated once by `PipelineConfig`. The engine result is the input for A8b; `missing_target_tables` checks it before any write. | AT-A8a, AT-A8b. | Drop the validator call: AT-A8a's typo config exits 0. |
| 7 | TOCTOU on a path | N/A: A8b reads the in-memory outputs and the sink's engine-written set, not the file system. | | |
| 8 | Weak tests and overclaimed evidence | Each acceptance test is labeled fail-before or no-regression pin. AT-A3/A6, AT-A5b and AT-A9 state their exact role. The A5 flight and census are void with zero activations. Every new walk is shown red on a seeded violation. | The builder records the base-commit result of each fail-before test in the PR body. | Run the OQ-3 flight with the companion unloaded: zero activations, so the evidence is void and the gate refuses it. |
| 9 | Refactor drift | D9 and the A9 deletion must not change behavior; the emit helper collapse (E-S1b) keeps each `emit_*` call. | Existing unit tests for `dp_session` and the run summary stay green on T1; AT-A9; AT-D9; `test_context_emit_dispatch.py`. | Swap two method names in the dispatch: the emit test fails. |
| 10 | Frozen contract drift | D9 removes an old public import path, recorded in `docs/frozen-surfaces.md` and the changelog in E-F1. Engine reason codes are append-only, in existing namespaces only: `config.target_table_unknown` (`E:reasons/config/_part2.py`, beside `TARGET_SHARED_DESTINATION` at `:77`) and `runtime.reference_table_unavailable` (`E:reasons/runtime/_part2.py`, beside `TRANSFORM_SOURCE_MISSING` at `:270`). No new namespace. The CLI has no reason registry; its new code `target.table_missing` sits beside its owner in `C:cli/io/_target_presence.py`. CLI exit codes move: A8a from exit 0 to exit 1, A2 and A8b from exit 0 to exit 3, all through `exit_code_for`. | Engine: AT-D9, `ET:sentry/release/test_frozen_surface_map.py`, `ET:sentry/test_reason_registry.py`, `ET:sentry/test_reason_baseline_frozen.py`. CLI: `CT:unit/test_exit_code_for.py` (recorded exception-to-exit table), `CT:sentry/defects/test_exit_code_owner.py` (one exit map), AT-A8a, AT-A8b. | Add an engine code without its registry row: `test_reason_registry.py` fails. Add `TargetTableMissingError` to `usage_error_types()`: `test_exit_code_for.py` gets 1 where the recorded row expects 3. |

Dev-rules recurring-defect catalog (11 classes), checked against this row: (1) anchored validation: no regex added; target keys are compared as exact set members. (2) strict wire types: no persisted model added. (3) no exception context: A2's coded `ExecutionError` and A8b's `TargetTableMissingError` are raised after the `except` closes, and AT-A2 and AT-A8b assert `__cause__` and `__context__` are None. (4) versioned read models: none added. (5) normalized scanners: the `swallowed-broad-except` predicate lists its covered shapes (section 5), with one seeded cell per shape, including `builtins.Exception`, tuples, `suppress` and `contextlib.suppress`. (6) private imports: the CLI imports only public engine names; the vendored predicate is a pinned copy, not an import. (7) hidden CI failures: the sentry runs in the normal suite with no report-only mode. (8) one trust class per entry point: N/A, no new entry point. (9) mutations on the final head: the gate reruns section 7 mutations on the exact head. (10) allowlisted helpers: no sentry allowlist is added; the baseline is per file. (11) no raised caps: nothing raises a `max`, ceiling or size cap; see OQ-PF2 for the one file that would cross a cap.

## 8b. Enumerations (from the code at the bases)

### Routes

- A5 is the unified-slice route only (`E:execution/_unified_slice.py:370`).
- A8b: the engine routes in section 4 (full frame, sequential, mixed, unified slice, out-of-core and chunked with a sink, isolated child, generation only).
- A8a: config validation in `E:config/_pipeline.py:490`, before any route choice.

### Exit paths

- A8a: a coded config error, CLI exit 1, at config check and in `decoy validate` (gate findings through `C:cli/gate/_layers.py:150-158`).
- A2: `ExecutionError` with `runtime.reference_table_unavailable`, raised after the `except` closes; `decoy run` exit 3 through `exit_code_for`. (Tokenize maps any `ExecutionError` to exit 1 in its own arm at `C:cli/tokenize.py:388`; that literal-exit arm is pre-existing and owned by row 24ze G-C1, not this row.)
- A5, A6, A7: the original exception propagates; CLI exit 3 (runtime) through `exit_code_for`.
- A8b: `TargetTableMissingError` (`target.table_missing`), exit 3 through `exit_code_for`, before any write; in tokenize before the vault commit, through its own arm.
- Emit helpers: no exit change; a raising logger method is swallowed and logged at DEBUG.

### FK shapes

- N/A: no FK behavior changes; the FK dtype catches are kept and recorded in section 1.

### Fields (every key this plan adds or reads)

- No config key is added. A8a validates the keys of the existing `targets` map against table names.
- No result or report field is added. D5 forwards four existing `run_pipeline` keywords (`C:cli/run/_execute.py:448-457`).

### Output surfaces

- Masked output bytes: unchanged.
- Files on disk: A8a and A8b now refuse runs that exited 0 with a missing file; neither writes a partial set.
- Logs: A5 removes the `_REROUTE_LOG` line (`E:execution/_unified_slice.py:75`) for exceptions outside `_REROUTABLE`; A2 removes one warning (`E:transforms/geo_generalize.py:281`).
- Public API: D9 removes the `quality.dp_budget.OpenDpReleaseSession` path (`E:quality/dp_budget.py:507`).

### Lists

- `write_targets` callers: `C:cli/run/_execute.py` `_write_mask_outputs` (`:390`, itself called from `C:api.py:653` and `C:cli/tokenize.py:375`) and `C:cli/demo.py:293` `_write_mask_outputs`. DELIV C2a keeps the tokenize and API old path until C4; demo remains separate. RUN-STREAM C1a adds `seal_result` for run routes. `missing_target_tables` is shared by `seal_result` and `write_targets`, and demo reaches it through `write_targets`.
- `_REROUTABLE` members: `pyarrow.ArrowInvalid`, `pyarrow.ArrowTypeError`, `MemoryError`. Coded declines: none. `build_live_physical_plan_inputs` (`E:execution/physical/_live_inputs.py`) has no `raise`; `compile_physical_plan` raises only `AssertionError` (`E:execution/physical/_compiler.py:272`, `:339`, `:381`) and the oracle's own capacity error through `require_resident_fit` (`E:execution/pipeline/_resident_fit.py:153`).
- Early schema codes in `decoy run` (`EARLY_SCHEMA_CODES`): `config.target_shared_destination`, `config.target_table_unknown`. `early_schema_findings` callers: `C:cli/run/_prepare.py:22,294`, `C:cli/compile_explain.py:188`; re-exported at `C:cli/gate/__init__.py:13,42`.
- `emit_*` helpers: `emit_step`, `emit_lineage`, `emit_fidelity`, `emit_quarantine`, `emit_throughput_sample`. Three remain after B5.
- `swallowed-broad-except` baseline keys: one per `src/` file with a counted site (about 77 engine, 27 CLI at the revision 5 bases), each with a `reason` and a `max`.

## 8c. Reuse inventory and frozen contracts

- Reuse: the engine's `PipelineConfig._targets_distinct` validator and `duplicate_target_groups` helper; the ratchet (`tests/sentry/_ratchet.py`, `scripts/dev/ratchet_check.py`) with its `approved_growth` route, and `test_baseline_registry.py` in both repos; the CLI exit map `exit_code_for` and its recorded table; the CLI early schema refusal in `C:cli/gate/_layers.py`; the oracle error constructors in `E:execution/_errors.py`; the CLI vendoring pin `ci/vendored.toml`; `scripts/test_flight.py` for OQ-3; the existing boundary test file `ET:physical/test_unified_slice_exception_boundary.py`.
- Frozen contracts touched: `docs/frozen-surfaces.md` (D9 in E-F1); the engine reason registry (two added codes in the existing `config` and `runtime` namespaces); one CLI code beside its owner (`target.table_missing`); the CLI exit map `exit_code_for` (one added row); CLI exit codes (A8a moves a typo config from exit 0 to exit 1, A2 and A8b move a run from exit 0 to exit 3). The public CLI gate export `shared_destination_findings` is renamed `early_schema_findings` (pre-GA hard delete; callers are in-repo only). Masking output is unchanged.

## 8d. Pre-mortem

| Risk | Guard |
|---|---|
| A5 turns a rare native exception into failed customer runs | The OQ-3 flight with a counted instrument and a non-zero activation count; the census; E-F2 can ship on a later train than E-F1. |
| A8b fires on a route that legitimately streams a table | The check counts the engine-written set; AT-A8b covers each route. |
| Removing the A5 catch exposes a lane error type the oracle does not raise | The census parity table and AT-A5b; each mismatch is fixed at the lane raise site through the oracle's constructor in `E:execution/_errors.py`; past the slice budget the builder stops for a re-scope (section 3). |
| A deliberate new broad boundary in another row (DELIV C3) meets the ratchet with no headroom | The `approved_growth` route with a dated owner decision, named in section 5 and in the DELIV and RUN-STREAM amendments. |
| A8b lands before its choke point exists | C-F1b waits for DELIV C2a and RUN-STREAM C1a (section 10). |
| A8b's additions push `C:cli/io/_targets.py` past the CLI 800-line cap | OQ-PF2: the predicate and error get their own module; the builder re-measures after DELIV C2a lands. |
| The ratchet baseline grows when a counted handler moves files | The ratchet refuses a new key; the split narrows the handler (section 5). |
| C-F1a waits a long time for a widened surface release (PR 821) | OQ-PF1: C-F1a waits on the first CLI repin that carries E-F1, not on the surface stack. |
| `E:transforms/geo_generalize.py` (588 lines) passes 600 with A2 | The builder keeps it at or under 600 (the catch and warning go, the coded raise and lazy load come in); over 600 needs a census entry the plan does not authorize, so the builder stops and reports. |

## 9. Placement

Checked against the engine and CLI CODEMAP "Where Things Go".

| New or moved thing | Path | CODEMAP row | Beside | Size now (lines) and expected |
|---|---|---|---|---|
| A8a validator and code | target-name helper in `E:config/_targets.py`, called by `PipelineConfig._targets_distinct` in `E:config/_pipeline.py`; `config.target_table_unknown` in `E:reasons/config/_part2.py` | Config models | `duplicate_target_groups` and `TARGET_SHARED_DESTINATION` | `_targets.py` 185, about +15; `_pipeline.py` 540, about +5 |
| A2 coded error and lazy load | `E:transforms/geo_generalize.py`; `runtime.reference_table_unavailable` in `E:reasons/runtime/_part2.py` (576 lines, about +4), `ExecutionError` block | transforms (owning module) | `_build_state_map` | 588; must stay at or under 600 |
| A3, A6 catch deletions | `E:plan/_seed_envelope.py`, `E:execution/physical/_compiler.py` | owning modules | | 367 and 450, each a few lines smaller |
| D9 deletion | `E:quality/dp_budget.py`; docstrings in `E:quality/dp.py`, `E:quality/dp_session.py` | quality | | 520, about -20 |
| A5 reroute set | `_REROUTABLE` in `E:execution/_unified_slice.py` | execution (owning module) | the handler it narrows | 473, about +15 |
| `_checks.py` narrowing | `E:plan/_checks.py:637` | plan | | 697 against its 700 pin (`ET:sentry/test_module_size.py:107`); no growth |
| A5 tests | `ET:physical/test_unified_slice_exception_boundary.py` | Physical seam tests | the existing test rewritten at line 213 | |
| Swallowed-broad-except predicate | engine `tests/sentry/defects/_swallowed_except.py`; CLI vendored copy at the same path, pinned in `ci/vendored.toml` | recurring-defect class rules in `tests/sentry/defects/` | `tests/sentry/defects/_defect_scan.py` | about 80 |
| Swallowed-broad-except sentry and baseline | `tests/sentry/defects/test_swallowed_broad_except.py` and `tests/sentry/baselines/swallowed-broad-except.json` (both repos); one `sentry_registry.toml` row each | same; baselines live in `tests/sentry/baselines/` | other `defects/` sentries | |
| A7 plain import | `C:cli/init.py` | CLI commands | `_validate_scaffold` | 739, a few lines smaller |
| A9 deletion, D5 | `C:cli/run/_render.py`, `C:cli/run/_execute.py` | CLI run | | 239 and 540, both smaller or flat |
| A8b check and error | `missing_target_tables`, `refuse_missing_targets`, `TargetTableMissingError` and the code constant `TARGET_TABLE_MISSING = "target.table_missing"`. Source plan: `C:cli/io/_targets.py`. Recommended (OQ-PF2): a new private module `C:cli/io/_target_presence.py` beside it, exported through `C:cli/io/__init__.py`; one row in `exit_code_for` (`C:cli/exit_codes.py`); one arm in `C:cli/tokenize.py` | CLI io; Exit codes | `write_targets`; `LayoutError` | `_targets.py` is 793 against the CLI `LIMIT = 800` (`CT:sentry/layout/test_module_size.py:19`); new module about 50 |
| A8a early refusal | `EARLY_SCHEMA_CODES` and `early_schema_findings` (renamed from `shared_destination_findings`) in `C:cli/gate/_layers.py`; callers `C:cli/run/_prepare.py`, `C:cli/compile_explain.py`, export `C:cli/gate/__init__.py` | CLI gate | `_schema_findings` | 553, about +3 |
| A8 tests | `CT:unit/cli_fmt/test_target_table_unknown.py`, `CT:unit/cli_fmt/test_write_targets_missing_table.py` | `tests/unit/cli_fmt/` | other target tests | |

Every new element has a present consumer in the same slice; no slice merges a helper for a later slice.

## 10. Slices

Production files exclude tests, baselines, docs and CI YAML. Each slice stays at or under 10 production files and 800 changed lines; a slice that grows past either splits at the boundary its row names.

| Slice | Repo | Carries | Prod files (est.) | Lines (est.) | Risk | Depends on |
|---|---|---|---|---|---|---|
| E-F0 (merged, engine #617) | engine | Section 2.1 of the source plan: the `text_mask` leak fix | | | R2 | done |
| E-F1 | engine | A2 (coded error, load only when `state` is asked for), A3, A6, A8a, D9 (A4 closed on main); engine `swallowed-broad-except` predicate, sentry, baseline and registry row (tests only, written last so the A2 and A6 deletions are not baselined); AT-A2, AT-A3/A6, AT-A8a engine half, AT-D9, AT-SBE engine | 10 (`transforms/geo_generalize.py`, `plan/_seed_envelope.py`, `execution/physical/_compiler.py`, `quality/dp_budget.py`, `quality/dp.py`, `quality/dp_session.py`, `config/_targets.py`, `config/_pipeline.py`, `reasons/config/_part2.py`, `reasons/runtime/_part2.py`); at the cap, so any further file splits the slice at the A8a boundary | ~300 | R2 (D9 removes an old public import path; A8a adds a config refusal) | E-G1 (merged, #688) |
| E-F2 | engine | A5: census with the AT-A5b parity table, `_REROUTABLE`, AT-A5, AT-A5b, AT-A5c; also narrows the `except Exception: continue` at `E:plan/_checks.py:637` to `decoy_engine.errors.ValidationError` (AT-CHK) | 2 (`execution/_unified_slice.py`, `plan/_checks.py`), plus one per lane raise site the parity table names (section 3); past 10 files or 800 lines the builder stops for a re-scope | ~220 before parity fixes | R2 (a native-lane exception now fails the run) | E-G1 (merged); OQ-3 flight and census evidence |
| C-F1a | CLI | A7, A8a early refusal (`EARLY_SCHEMA_CODES`), acceptance and gate-location pin (AT-A8a CLI half), A9, D5; lowers the CLI `swallowed-broad-except` `max` if C-G2 merged first | 7 (`cli/init.py`, `cli/gate/_layers.py`, `cli/gate/__init__.py`, `cli/run/_prepare.py`, `cli/compile_explain.py`, `cli/run/_render.py`, `cli/run/_execute.py`) | ~200 | R2 (exit code change on a config that exits 0 today) | the CLI repin that carries E-F1 (OQ-PF1); the open row 63a RUN-STREAM CLI slices (C1l, C1a, C1b) that edit `_execute.py` and `_render.py` merge first |
| C-F1b | CLI | A8b: `missing_target_tables` over every declared target type, `TargetTableMissingError` and its `exit_code_for` row, the calls in `seal_result` and `write_targets`, the tokenize call before the vault commit and its arm, run refusal registration and code promotion with the coded-exception sentry, demo onto the shared check and coded emitter, the dead demo guard; AT-A8b including the cloud cell | 8 (`cli/io/_target_presence.py` new under OQ-PF2, `cli/io/__init__.py`, `cli/io/_targets.py`, the module holding `seal_result`, `cli/run/_errors.py`, `cli/exit_codes.py`, `cli/tokenize.py`, `cli/demo.py`) | ~260 | R2 (exit code change) | row 61 DELIV C2a and row 63a RUN-STREAM C1a merged; the section 4 amendments applied to both plans |

The emit-helper item and its AT-EMIT ride the source plan's E-S1b (24zj lane, unchanged by PR 821).

Ordering:

- E-F0, its own daily engine release and its CLI repin landed first (done).
- E-F1 and E-F2 form the fix lane. They run in parallel with the guard and surface lanes in separate worktrees. They share no file with E-S1a or E-S1b.
- C-F1a waits on the CLI repin that carries E-F1 (A8a acceptance) and on row 63a's `_execute.py` and `_render.py` writers. C-F1b waits on rows 61 and 63a. `demo.py` is shared with C-S2 (24zk), so whichever merges second rebases.
- The CLI `swallowed-broad-except` baseline is written in C-G2 (source plan, guard lane), which needs E-F1 merged for the vendored predicate.

Testing per slice (owner test-depth rule): T0 per edit, T1 impact selection per commit, gates run T1 on the exact head. Full suite only on an escalation trigger: E-F1 (frozen contract: D9 removes a public import path). All runs on the Mac or a VM through `~/bin/vm-run`, never on the devbox. Mutation testing on the A5 narrowing, the A8b check and the A8a validator (core logic). The `swallowed-broad-except` predicate carries the named mutations of section 7.

## 10a. Ratchets touched

Nothing in this row raises a `max`, adds a key to an existing baseline, or raises a module-size ceiling. A slice that finds it must do so stops and reports.

- **E-F1**: adds `swallowed-broad-except` (new, written after the A2 and A6 deletions). Reason registry grows by `config.target_table_unknown` and `runtime.reference_table_unavailable`, appended in existing namespaces. Module-size: a LEGACY (over 700, exact) entry of a file that shrinks moves down to the new count. A DENSE entry moves only if the file is now more than 40 lines under its ceiling, and then to `ceiling_for(loc)`, never to the raw count. `docs/frozen-surfaces.md` shrinks by the D9 path.
- **E-F2**: the `except Exception` arm in `src/decoy_engine/execution/_unified_slice.py` becomes `except _REROUTABLE`, so that file's `swallowed-broad-except` `max` drops by one (or the key goes if it was the file's only site). `src/decoy_engine/plan/_checks.py` drops by one the same way.
- **C-F1a**: CLI `swallowed-broad-except` `max` drops for `src/decoy/cli/init.py` (A7) and `src/decoy/cli/run/_render.py` (A9), if C-G2 has merged.
- **C-F1b**: no CLI reason registry exists; the code constant is new in `_target_presence.py`. `CT:unit/test_exit_code_for.py` gains one recorded row; `exit-code-owner.json` stays empty. No module-size cap moves (OQ-PF2).
- **Any other row** that adds a deliberate broad boundary: new key through `approved_growth` only (section 5).

## 11. Release and CLI repin

- E-F1 and E-F2 are engine changes. Each ships on the next engine release after it merges. The source plan put E-F1 in the "Surface release" (0.29.0 or the next free version) with E-S1a, E-S1b and E-S1c, and E-F2 in it "if merged by then, else the next train". OQ-PF1 keeps that when the surface release is close and otherwise lets E-F1 ride an earlier daily train.
- The release notes name A8a (new config refusal, exit 1), A2 (coded runtime refusal on a broken install, exit 3), A5 (native-lane exceptions now fail the run, except the named reroute set) and D9 (removed import path).
- CLI repin: the CLI moves from `decoy-engine==0.28.3` to the release carrying E-F1 (engine repin checklist). C-F1a lands on that pin. C-F1a and C-F1b ship in CLI 1.0.0.

## 12. Owner questions

Decided in the source plan (2026-11-16, A5 set re-decided 2026-11-17), unchanged:

- OQ-1. Scope split: do all nine A items in this batch, although the CLI post-1.0 plan (#284) lists A2, A5, A6, A7 and A9 as 1.x patch. Decided: yes.
- OQ-3. Let an unexpected native-lane exception fail the run instead of rerunning on pandas. Decided: yes, after the section 3 flight shows no reroute from a non-coded exception with a non-zero activation count.
- A5 reroute set. Decided: `MemoryError`, `pyarrow.ArrowInvalid` and `pyarrow.ArrowTypeError` keep rerouting with the coded declines (round 2: the code shows no coded decline in the two plan callees, so that group is empty and deleted; section 3); all else propagates. Reason: each one is a run the oracle completes today (#308), and failing it would be a function break.
- OQ-7. A target key that names no table is a config error: exit 1 at config time (A8a). A declared table that the engine did not produce is a runtime failure: exit 3 at the post-engine choke point (A8b). Decided: yes to both.

New in this extract (technical, kind: default; also recorded in vault [[OWNER-QUESTIONS]]):

- OQ-PF1. Release for E-F1 now that engine PR 821 widens 24zj. PR 821 lands the CLI repin "atomically" with "the engine release with W0 through W7", so a surface release that waits for the whole W stack would hold C-F1a's A8a acceptance for weeks. Options: (a) E-F1 and E-F2 ship on the first engine daily train after they merge, as E-F0 did, and C-F1a depends on the first CLI repin that carries E-F1. (b) Keep E-F1 in the surface release. **Recommended: (a).** It changes only release timing, not design, and the E-F1 refusals (A8a, A2) are V1 correctness fixes that should not wait on a surface cleanup.
- OQ-PF2. Where `missing_target_tables`, `TargetTableMissingError` and the code constant live. `C:cli/io/_targets.py` is 793 lines at CLI `3df9c13a`; the CLI module-size `LIMIT` is 800 and the file has no size entry, so adding them there breaks the cap. Options: (a) a new private module `C:cli/io/_target_presence.py` beside `_targets.py` holds both; `write_targets` and `seal_result` import from it. (b) Keep them in `_targets.py` and shrink the file first. **Recommended: (a).** One small module for one predicate is the smallest change that keeps the cap, and it still gives one choke point. The builder re-measures at the C-F1b base, because DELIV C2a edits `_targets.py` first.

## 13. Follow-ups outside this row

- Each `swallowed-broad-except` row labeled "unclassified catch-all" is open 24zi debt. The E-F1 and C-G2 build reports list them; the orchestrator files them as V2-LOG unless one turns out to hide a V1 failure, which then gets its own row.
- The post-1.0 plan rows for A1 to A9, D5 and D9 are marked done as each slice merges.
- The section 4 amendments go into the RUN-STREAM and DELIV plan files.
- The source plan revision 7 table rows keep the older anchors listed in "Changes in this extract"; the orchestrator may fold the corrections into the source plan when it next edits it.
