Status: plan

# PROP batch: quiet fallbacks, unused public names, shims and guard facts (roadmap rows 24zi, 24zj, 24zk, 24zl)

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `proportionality.md`, `cross-cutting-concerns.md`,
`api-and-compatibility.md`, `testing.md` (test depth); engine `CLAUDE.md`, `CODEMAP.md`
("Where Things Go"), `docs/frozen-surfaces.md`, `docs/compatibility-contract.md`,
`docs/strategies.md`; CLI `docs/ROADMAP.md` (rows 24zd, 24ze, 24zi to 24zl, 61, 63a, 93), CLI
`CODEMAP.md`, CLI `docs/roadmap/post-1.0-plan.md`; CLI plan branch `plan/run-stream-r6-5`
(`docs/plans/2026-11-08-run-stream.md`) and engine `plan/deliv` (`docs/plans/2026-11-12-deliv.md`);
owner memory rules: V1 bar, process by risk (2026-11-10), sentry over prose, pre-release no
locking, no new features (2026-11-16).

Revision 4: the Codex NO-GO after revision 3 (one `V1`, one `V2-LOG`) is remediated;
section 16 maps both findings to their fixes. Dennis round 2 remains mapped in section 15.
OQ-1 through OQ-7 stay decided.

Bases (2026-11-16): engine `origin/main` `13c95c7de` (includes 0.27.0, RUN-STREAM E5a #604 and
E5b #605); CLI `origin/main` `ba7b613e` (pins `decoy-engine==0.27.0`); platform `origin/main`
`fbaee2a9` (pins `decoy-engine==0.18.0`, parked; read only to record consumers). Input: the audit
`C:docs/records/2026-11-15-proportionality-audit/REMEDIATION.md` sections 4, 5, 7, 8, 14 and
15. The audit was read at engine `64e9349b` and CLI `e716f445`; every line number below was
re-read at the bases above and some differ from the audit.

Notation: `E:` is engine `src/decoy_engine/`, `ET:` is engine `tests/`, `C:` is CLI
`src/decoy/` (and `C:` plus a repo path such as `C:docs/` for CLI repo files), `CT:` is CLI
`tests/`.

## 0. Why this plan is in the engine repo

Of the 18 build slices below, 11 land in the engine: the new first slice E-F0, all of package B,
most of A and D, and the engine half of E. The 7 CLI slices are smaller, and five of them do not
depend on an engine release. The plan sits in the repo that holds most of the work so the gate has
one place to look; each CLI slice names its CLI paths in full.

## 1. Pinned guarantee and non-goals

Guarantee. After this batch:

- (a) no `text_mask` span is written back with its real value unless its strategy is
  `passthrough`, and no detector and strategy pair that the code cannot carry out compiles;
- (b) no failure listed in 24zi turns into a weaker output while the run reports success;
- (c) every public engine name listed in 24zj has a recorded consumer or is gone;
- (d) no CLI line probes for an engine name that the exact pin already ships, and no engine
  module exists only to re-export or forward to another;
- (e) each guard fact listed in 24zl is written in one place, and a new comment that carries a
  task id, review round, dated decision or reviewer name fails a guard.

Non-goals:

- No new feature. Each item is a fix to existing behavior or a deletion.
- D13 (`_V2_CUSTOM_PROVIDERS` beside `_CUSTOM_FAKER_PROVIDERS`) is not a shim: both tables are
  live. It goes to the post-1.0 plan as a duplication item.
- B9 (platform reason codes) stays as the platform wire contract. Reason codes are append-only.
- E5 (exact line pins on four legacy CLI files) stays until V1 (owner 2026-11-15). E8 is V1+.
- The broad catches in `E:execution/_chunked_fk_dtype_safety.py` stay. They fail closed (return
  False, which refuses the edge), and narrowing them safely would have to name `OSError`
  (`ZoneInfo("America")` raises `IsADirectoryError` on Python 3.10) and `AttributeError`
  (`pa.decimal32` is absent before pyarrow 18; the floor is `>=14`). Recorded as kept, not fixed.
- Audit packages C, F, G, H, I and J are not in these rows.
- No platform change. The platform is parked on engine 0.18.0. A name it uses is kept and the
  consumer is recorded.
- Compatibility window: `api-and-compatibility.md` asks for a documented window before a removal.
  The owner's pre-GA hard-delete rule (row 24zk text) is that window: no 1.0 has shipped, and the
  0.29.0 release notes list every removed name. E-F0 ships alone on the preceding daily train.

## 2. Row 24zi PROP-FALLBACK

No item is fixed on main.

### 2.1 Live leak found in review (slice E-F0, first in the batch)

`text_mask` dispatches each span on its strategy with no check that the strategy fits the
detector:

- `_mask_date_shift` (`E:transforms/text_mask.py:434-465`) returns `matched_text` unchanged when
  the span does not parse with `_COMMON_FORMATS`. `per_detector_strategy: {ssn: date_shift}` or
  `{email: date_shift}` therefore writes the real SSN or email into the output (Dennis probed it).
  The same branch leaks a real date-like span supplied through the library `extra_spans` API when
  the span does not parse (for example `2024-02-30`). The default config produces no date spans:
  there is no built-in date detector, and NER emits no date id.
- `_mask_fpe` reads `_FPE_CONFIG.get(detector_id, ("digits", None))` (`:349`), so `fpe` on any
  detector runs a digits cipher whatever the span holds.
- `faker` on a detector with no `_FAKER_METHOD` entry writes a fake person name (the audit's A1).
- An unknown strategy name falls through to the redact token in `_mask_span` (`:505-507`).
- Unknown detector ids in `detectors:` are skipped silently (`docs/strategies.md:380`), and an
  unknown key in `per_detector_strategy` is never read, so a typo leaves that type of span on its
  default.

The first is a real value shown in output: V1, and it blocks. The fix is one predicate and one
compile check:

- `strategy_supported(detector_id: str, strategy: str) -> bool` in `E:transforms/text_mask.py`.
  `faker` needs a `_FAKER_METHOD` entry, `fpe` an `_FPE_CONFIG` entry, `date_shift` a date
  detector (the detectors whose `DETECTOR_DEFAULTS` value is `date_shift`: `iso_date`, `us_date`,
  `eu_date`), and `redact` and `passthrough` accept any id in
  `TEXT_MASK_STRATEGY_DETECTORS`. Any other strategy name is unsupported. The private strategy
  tables stay private: only this module reads them.
- `_mask_span` calls the predicate first and raises a coded error for an unsupported pair (it is
  reached only by a caller that skipped compile, such as a direct `mask_cell_with_spans` call).
  The runtime type is the existing `ConfigError`, tagged with
  `config.mask.text_mask_strategy_unsupported`; the raw error maps to CLI usage exit 1. The
  full-frame handler at `E:execution/_strategies/_text_mask.py:228` currently wraps only
  `FpeUnencryptableError`, so E-F0 adds an exact catch that converts this error to the oracle's
  value-free `StrategyError` after the catch has closed. No cause or context chain survives.
  `_mask_fpe` then indexes `_FPE_CONFIG[detector_id]` with no default. Remove the second
  `("digits", None)` default in `_apply_sub_floor_span_policy` at `text_mask.py:308` too.
  `E:execution/native/_text_mask_native_fpe.py:41` also imports `_FPE_CONFIG`; its eligibility
  lookup stays an exact table lookup and gains no fallback.
- `_mask_date_shift` on a span that does not parse returns the redact token (`cfg["token"]`,
  default `[REDACTED]`), never the input. A parse failure on real data is common enough that a
  raise would break runs, and the token is safe.
- The compile check `check_text_mask_strategies` in `E:plan/checks/_text_mask_strategy.py`,
  wired in `E:plan/_compile.py` beside `check_text_mask_ner_available` in both the full and the
  config-only check lists. It uses two derived inventories, not one hand-written list:
  `SELECTABLE_TEXT_MASK_DETECTORS` is the public `SPAN_DETECTOR_IDS` derived directly from
  `_SPAN_DETECTORS` in `E:detection/detectors.py`, and is the exact set permitted in `detectors:`.
  `TEXT_MASK_STRATEGY_DETECTORS` is the union of that set, the values of the existing
  `NER_ENTITY_MAP` in `E:detection/ner.py`, and the keys of `DETECTOR_DEFAULTS`. The last source is
  the existing Tier 2 library `extra_spans` dispatch inventory documented beside
  `DETECTOR_DEFAULTS`: library callers may inject those ids even when config cannot select them as
  built-in detectors. For each `text_mask` column the check refuses (1) an id in `detectors:` that
  is not in `SELECTABLE_TEXT_MASK_DETECTORS`, (2) a key in `per_detector_strategy` that is not in
  `TEXT_MASK_STRATEGY_DETECTORS`, and (3) a pair for which `strategy_supported` is False. Both
  arguments must be strings; non-string ids and strategies are refused rather than coerced.
  `config.mask.text_mask_detector_unknown` is used for both inventory failures because in both
  cases the id is unknown to that config field; the field path distinguishes `detectors` from
  `per_detector_strategy`. No separate reason code is needed.
- The inventory guard proves equality and derivation, not a subset: `SPAN_DETECTOR_IDS` equals
  `frozenset(_SPAN_DETECTORS)` in its owning module,
  `SELECTABLE_TEXT_MASK_DETECTORS == SPAN_DETECTOR_IDS`, and
  `TEXT_MASK_STRATEGY_DETECTORS` equals the union above. Its realistic mutation replaces the
  selector inventory with `frozenset(DETECTOR_DEFAULTS)`, which must make AT-A1g fail.
- Two new engine reason codes, both value-free (they name the column, detector id and strategy):
  `config.mask.text_mask_strategy_unsupported` (cases 3 and an unknown strategy name) and
  `config.mask.text_mask_detector_unknown` (cases 1 and 2). They are added `UNRELEASED` and
  stamped at release (REG-RELEASE). `config.mask.unknown_strategy` is not reused: it belongs to
  the column-level `strategy:` key.
- `docs/strategies.md:380-386` changes from "Unknown IDs are skipped silently" to the refusal,
  and lists the supported pairs.
- Update every statement of the old leak behavior: the draw-site catalogue at
  `E:execution/native/_draw_sites_mask.py:293`, `text_mask.py:447-448`, and the out-of-core oracle
  wording at `E:execution/out_of_core/_mask_group_c.py:224-225`. Re-pin only the
  `mask.text_mask_date_shift` entry digest and the overall catalogue digest in
  `ET:native/test_draw_sites_catalogue_pinned.py`, with a comment that the reason is the changed
  unparseable-span contract. No other catalogue entry moves.
- The check runs beside `check_text_mask_ner_available` and tail-appends
  `text_mask_strategies` to all three reported check lists in `E:plan/_compile.py`: the
  no-profile `checks_passed` tuple beginning at `:295`, the profiled tuple beginning at `:371`
  (the review's `:348` anchor; `:371` at base), and the config-only return beginning at `:565`
  (`:566` is its first entry). `E:plan/_serialize.py:221` serializes `checks_passed`, so every plan
  YAML gains this final item. The compile-check ownership row names `check_text_mask_strategies`
  as config-only and present in full, no-profile and config-only compilation. Move the pins in
  `ET:unit/plan/test_compile_basic.py:79`,
  `ET:unit/plan/test_compile_s2_refactor.py:72,189` (including positional `[-18]`), and
  `ET:acceptance/test_f06_declared_casting.py`'s `plan_yaml_at_baseline`; add a changelog fragment
  that records the plan YAML addition and the new refusal.

Shipped-surface inventory at the pinned bases found no migration. Engine `docs/strategies.md`,
`docs/proof-manifest.json`, and the two `text_mask` testflight manifests select only `ssn`,
`email`, `us_zip`, or `us_phone`, all keys of `_SPAN_DETECTORS`. CLI `ba7b613e` bundled templates,
examples, and `decoy init` scaffold sources emit no `text_mask.detectors` list. Therefore E-F0
changes the detector-contract wording and adds refusal tests, but changes no shipped template,
init output, testflight manifest, proof manifest, or existing docs example config.

Test fixtures that use unsupported pairs today move to supported ones (section 8, AT-A1f).

### 2.2 Items

| Item | Site (at base) | Defect | Reachable | V1 behavior | Slice |
|---|---|---|---|---|---|
| A1 | `E:transforms/text_mask.py` `_mask_faker` | The audit named the inner `try` in `_mask_faker`. That catch is unreachable (`shared_faker()` is a default-locale `Faker()`). The reachable defect is section 2.1. | Yes, through section 2.1. | Section 2.1. The inner `try` and its `fake.name()` fallback are deleted in the same slice. | E-F0 |
| A2 | `E:transforms/geo_generalize.py` `_build_state_map` (272-288) | A failed `load_table("us_zip5_city_state")` returns `{}` with a warning, so every state value is `""`. | Only on a broken install (the table ships in the wheel). | The load error propagates. | E-F1 |
| A3 | `E:plan/_seed_envelope.py` (~127) | `except _ProviderError: reg_caps = None`. | No. `check_unknown_provider` runs first at `E:plan/_compile.py:190`, and in the config-only checks at 514. | Catch deleted. | E-F1 |
| A4 | `E:plan/checks/_generate_columns.py` `_expression_refs` | `except Exception: return frozenset()`: a bad expression becomes "no references". | No. `_check_parse_rules` runs before `_check_forward_references`, and `DerivedConfig.from_dict` already compiles the only `ref_kind="expression"` field. | Catch deleted. | E-F1 |
| A5 | `E:execution/_unified_slice.py` (359-361) | `except Exception` logs `_REROUTE_LOG` (`:74`) and returns None, so the caller reruns the slice on pandas. A native bug becomes a slower correct run. | Yes, on any exception in the callees listed in section 2.3. Output does not change (the pandas oracle is correct). | Section 2.3. Owner question OQ-3. | E-F2 |
| A6 | `E:execution/physical/_compiler.py` `_post_scan_resident` (~437-445) | `except Exception: return None` around `post_scan_resident_for(...)`, evidence only. The runtime calls the same function with no catch. | Only on an internal bug. | Catch deleted. | E-F1 |
| A7 | `C:cli/init.py` `_validate_scaffold` (~315-332) | `try: import yaml; from decoy_engine.config import parse_pipeline_config except Exception: return`. Both are hard dependencies, so a broken install skips scaffold validation. | Only on a broken install. | Plain import. | C-F1a |
| A8a | `E:config/_targets.py:161-173` `duplicate_target_groups` and `E:config/_pipeline.py:370` `PipelineConfig._targets_distinct`; the old CLI skip is `C:cli/io/_targets.py:487-489` | A `targets:` key that names no configured table is never refused; a source name alone is not a valid target key. `write_targets` skips it and the run exits 0 with no file. | Yes, from any config with a typo in a target key. | The engine config validator is the one refusal point. Beside `_targets_distinct`, it checks target keys against table names only, raises the new engine code `config.target_table_unknown`, and updates `duplicate_target_groups`'s docstring so it no longer says writers skip unknown keys. CLI run and validate both exit 1 before any source read. The gate location is `targets.{table}`, not `targets.{table}.format` (`C:cli/gate/_layers.py:213-215`). | E-F1; CLI repin and C-F1a acceptance |
| A8b | `C:cli/io/_targets.py` `write_targets` (`:461-495`); DELIV C2a retains `_write_mask_outputs` for `C:cli/tokenize.py:371` and `C:api.py:633` until C4; `C:cli/demo.py:295` has a separate `_write_mask_outputs`; RUN-STREAM C1a adds `seal_result` | A declared file target whose table the engine did not produce is skipped (`table = outputs.get(table_name); if table is None: continue`) and the run exits 0. Engine #584 (LOADER-DROP) closed one cause; the skip still hides any other. | Yes, on any engine result that lacks a declared table. | `missing_target_tables` is the one predicate. Both `seal_result` and `write_targets` call it before any write, so the retained tokenize, API and demo paths refuse too. Demo moves onto the shared check instead of owning a second rule. New CLI code `io.target_table_missing`, exit 3. Section 2.4. | C-F1b |
| A9 | `C:cli/run/_render.py` `_next_hint_for_run` (~53-61), used at ~168 | Reads `raw_cfg["output"]["path"]`, a key the V2 schema does not have, inside `try/except: pass`. Always None. | Dead code. | Deleted; the caller drops the keyword. | C-F1a |
| Emit helpers | `E:context.py` `emit_step` (99-164), `emit_lineage` (167-182), `emit_fidelity` (185-195), `emit_quarantine` (198-213), `emit_throughput_sample` (216-226) | Five copies of `getattr` probing plus `except Exception: pass`; `emit_step` also retries without `node_id` on `TypeError` (D12). No failure is counted: `sink_failures` (`E:progress.py:178`, `:198`; `E:_progress_events.py:376`) counts only `ProgressReporter` sink failures, not these helpers. | The catch is a deliberate observation boundary: a logger that raises must not fail a run. The five copies and the `TypeError` retry are the defect. | One private `_dispatch_sink` in `E:context.py` owns the probe and the catch; it logs the exception class name (value-free) at DEBUG on the engine logger and counts nothing (adding a counter would be a new feature). The `TypeError` retry goes. `emit_fidelity`, `emit_quarantine` and `node_id` go with B5. | E-S1b |

Failure modes:

- E-F0: a config that runs today with `faker` on email, `date_shift` on ssn, a misspelled
  strategy, an unknown detector id, or a library-only id such as `iso_date` or `person_name` in
  `detectors:` now fails compile with exit 1. This is the intended change. The same library-only
  ids remain valid keys in `per_detector_strategy`. `decoy validate` refuses the invalid selector
  forms too.
- E-F0: an unparseable date-like span supplied through library `extra_spans` now becomes the token
  instead of the real text. Default config, NER, native chunked, out-of-core native and SEQ routes
  cannot produce such spans from config at this base.
- E-F0: a span from a caller-supplied `extra_spans` list with an unknown id or unsupported pair
  raises in `_mask_span`. No production caller passes such spans; tests do, and they move.
- A5: a native exception that rerouted today now fails the run. Section 2.3 has the flight.
- A8b: a sink-route table the engine streamed to the sink is not in `outputs`; the check counts
  it as produced (section 2.4).
- A2: a working install sees no change, so the test injects a loader failure.

### 2.3 A5 detail (slice E-F2)

Callees inside the `try` (`E:execution/_unified_slice.py` ~188-352) and the verdict for each:

| Callee | On exception |
|---|---|
| `build_live_physical_plan_inputs` | propagate |
| `compile_physical_plan` | propagate |
| `_admission.resident_contract_admission` | propagate (admission declines are return values, handled before the try) |
| `build_unified_slice_activation` | propagate |
| `ShadowContext.from_key_provider` | propagate |
| `capture_shadow_snapshot`, `compute_when_masks` | propagate |
| `ShadowCoordinator(...).run` | The `FAKER_POOL_NON_STRING_OUTPUT` reroute arm at `:252-259` is unchanged; any other `ShadowDifference` raises `UnifiedSliceInvariantError`; anything else propagates |
| `assemble_node_evidence`, `deterministic_faker_pin_columns`, `reconstruct_source_shaped_output` | propagate |
| `_pipeline_finalize.stamp_execution_metrics`, `_pipeline_route_exec.execution_telemetry` | propagate |
| `_pipeline_finalize.finalize_validators_and_quarantine` | propagate (a validator failure is the same user error the oracle raises; AT-A5b) |
| `_typed_warnings`, `_typed_row_errors` and `ExecutionResult` construction | propagate |
| `PoolBuildFailed` handler | unchanged |

The builder lists every `raise` site reached from these callees. Any coded decline found (an
exception class carrying a registered reason code that means "this slice is not eligible") goes
into one tuple `_REROUTABLE` in `_unified_slice.py`, and only that tuple reroutes. If none is
found, the `except Exception` arm is deleted.

Instrument for OQ-3 (no production change): before E-F2 merges, the test flight
(`scripts/test_flight.py`, golden corpus plus the prodsim set) runs on engine main under a wrapper
that attaches a `logging.Handler` to logger `decoy_engine.execution._unified_slice` and counts
records whose message starts with `unified_slice_unexpected_exception_reroute`, grouped by
`exc_type`. The flight counts only if (1) `decoy_engine.native_companion_status()` reports the
companion loaded and (2) at least one run has
`quality_metrics["unified_slice_activation"]["activated"] is True` (`_unified_slice.py:334-335`).
A flight with zero
activations is void, not clean. The wrapper and the counts go into the E-F2 PR evidence.

### 2.4 A8b detail and plan amendments (slice C-F1b)

Placement. DELIV C2a (row 61, engine `plan/deliv` `docs/plans/2026-11-12-deliv.md`, lines 455-460)
turns the run route into a `DeliverySink.write_table` loop over `result.outputs`, but explicitly
keeps `_write_mask_outputs` as the old non-sink path for `cli/tokenize.py` and `api.py` until C4.
`cli/demo.py:295-303` owns another wrapper over `write_targets`. RUN-STREAM C1a (row 63a, CLI
`plan/run-stream-r6-5` `docs/plans/2026-11-08-run-stream.md`, lines 790-798) adds
`seal_result(outputs)` for run routes. It is not the only post-engine writer.

The check is one function, `missing_target_tables(config_dict, outputs, engine_written) ->
list[str]` in `C:cli/io/_targets.py`: declared file targets whose table is in neither `outputs`
nor the set of tables the engine wrote through the sink. `seal_result` calls it first and raises
`TargetTableMissingError` (`io.target_table_missing`, exit 3) before any write. `write_targets`
calls the same predicate first with an empty `engine_written` set, so tokenize, API and the old
run path refuse too. Demo deletes its local decision and reaches the same check through
`write_targets`. The one predicate and the two writer choke points are guarded together.

Amendment notes for the two plans (the orchestrator applies them to those plan files when this
plan passes the gate; they are written here so the change is reviewed once):

- RUN-STREAM `plan/run-stream-r6-5`, `2026-11-08-run-stream.md`, the `seal_result` bullet at
  lines 790-793: replace "A
  target key that names no output table expects nothing, as in today's `write_targets`
  (`:487-489`) and DELIV's file-target set" with "Every target key names a config table (PROP
  A8a refuses others at config time). A declared file target whose table is neither in `outputs`
  nor engine-written is refused by `missing_target_tables` with `io.target_table_missing`, exit 3,
  before any write (PROP A8b)."
- RUN-STREAM line 1160, AT-C1e: replace "a target key naming no output table (skipped, not
  refused)" with "a target key naming no config table (refused by PROP A8a) and a declared target
  whose table is missing from both resident outputs and the engine-written set (refused by PROP
  A8b before sealing)." Align the revision table at lines 197 and 226 with the same rule.
- DELIV `2026-11-12-deliv.md`, the C2a `run/_execute.py` bullet (lines 455-460): add
  "`write_targets` calls PROP A8b's shared `missing_target_tables` check before its first write.
  The retained tokenize and API callers therefore refuse until C4; RUN-STREAM's `seal_result`
  calls the same check for sink-aware run routes."

Engine routes and the every-declared-table guarantee. A8b is safe only if every route returns or
streams each config table. The routes, from `E:execution/`:

| Route | How tables reach the CLI |
|---|---|
| full frame (`_pipeline_full_frame.py`) | `outputs` dict, every config table |
| sequential (`_sequential.py`) | `outputs` dict |
| mixed (`_pipeline_mixed_route.py`, `_mixed_static.py`) | `outputs` dict |
| unified slice (`_unified_slice.py`) | `outputs` dict, or rerouted to full frame |
| out-of-core and chunked with a sink (`out_of_core/`, `_chunked_output_sink.py`) | written through the sink (engine-written set) |
| isolated child (`_isolated_reason.py` and the governor) | `outputs` from the child, or a terminal outcome |
| generation only | `outputs` dict |

This table is a claim to prove, not a finding. AT-A8b runs one two-table config per route and
asserts each declared table is in `outputs` or the engine-written set. A route that drops a table
is a finding for that route, fixed at the route; the check is never relaxed to pass it.

## 3. Row 24zj PROP-SURFACE

The CLI uses none of these names (`git grep` at `ba7b613e`). Platform hits are listed where they
exist.

| Item | Names | Consumers found | Verdict | Slice |
|---|---|---|---|---|
| B1 | `_F9_KEPT_BINDINGS` in `E:__init__.py` (~342-365): `BundlePool`, `CompositeAddress`, `PoolCache`, `composite_city_state_zip`, the `Ein`/`Mrn`/`Ndc`/`Npi`/`Ssn` `Adapter`, `Domain` and `Validator` names, `IdentifierError`, `IdentifierFormatError` | `ET:unit/test_identifiers_subimport.py:46-47` only; platform hits are archive logs | Delete the top-level bindings. The names stay importable from their own modules (`decoy_engine.identifiers` and the pool modules). | E-S1a |
| B2 | `deterministic_hash` (`E:internal/crypto.py:18`) | none in src; `ET:unit/internal/test_crypto.py`, and a row in `ET:sentry/test_deprecation_expiry.py` if present | Delete with its tests and any expiry row. | E-S1a |
| B3 | `ExecutionContext.resolve_connector`, `captured_outputs`, `pool_resolver`, `column_relationships`, `_exports`, `_current_node_id`, `export()` | none; the platform builds only `ExecutionContext(logger=...)` (`api/storm/router.py:1297`) | Delete. `logger`, `derive_key`, `pipeline_derive_key` and `instance_default_locale` stay (read by `E:execution/_pipeline_full_frame.py`, `_pipeline_mixed_route.py`, `physical/_shadow_generation.py`). | E-S1b |
| B4 | `TelemetryClient`, `ExecutionContext.telemetry` | none | Delete. | E-S1a |
| B5 | `emit_fidelity`, `emit_quarantine`, `emit_step(node_id=)` | tests only; platform `api/persistence/logger.py` implements the sink methods, on engine 0.18 | Delete the two helpers and the keyword. The sink methods the platform implements are its own names. | E-S1b |
| B6 | `ExecutionEvent` (`E:execution/_events.py`) | never built | Delete the module and both exports. | E-S1a |
| B7 | `run_pipeline` keywords `progress_interval_s`, `secret_registry`, `secret_cache_policy`, `stream_chunked_output` | no caller anywhere; `stream_chunked_output` has 12 src lines in 6 files and 3 test lines | Delete. `docs/compatibility-contract.md:43-50` names `secret_registry` and `secret_cache_policy` as additive and counts "42 frozen parameters"; that paragraph is updated (38 after the four removals) and records that `SecretCachePolicy` then has no per-run setter: the cache policy is the module default only. | E-S1b |
| B7 | `chunked_dispatcher_enabled`, `multi_table_dispatch_enabled` | platform `api/jobs/v2_runner.py:263-264` | Keep; record the consumer in `docs/frozen-surfaces.md`. | E-S1b (doc line) |
| B7 | `use_byte_estimate_routing`, `use_probe_routing` | `E:capacity.py` passes `False`; `E:execution/__init__.py` documents them as the rollback path; also read by the physical `_snapshot` | OQ-4 (decided: keep as documented rollback switches, consumer recorded). | E-S1b (doc line) |
| B8 | `FK_SELF_REFERENCE` alias at `E:validation_result.py:367`; `event_to_legacy_dict` (`E:_progress_events.py:598`, exported from `E:progress.py` and `__all__`) | tests only | Delete the alias (the code `fk.self_reference` stays). Delete `event_to_legacy_dict`; keep `_LEGACY_FIELDS`, which `event_to_dict` reads. E-S1a runs `ET:unit/test_reason_registry.py` and `test_reason_baseline_frozen` on its head. | E-S1a |
| B9 | platform reason codes | platform wire contract | Stays. | none |

Each deletion updates, in the same slice: `docs/frozen-surfaces.md`, `ET:unit/test_public_api.py`
(`test_all_lists_every_public_name`), `ET:unit/execution/test_r3_public_signature_freeze.py`
(B7 only), `docs/compatibility-contract.md` (B7 only), and `CHANGELOG.md` under "Removed".
`ET:sentry/release/test_frozen_surface_map.py` then proves the page matches `__all__`.

Failure mode: an outside user importing a removed name gets `ImportError` or `AttributeError`.
That is the intent before 1.0.

## 4. Row 24zk PROP-SHIMS

No item is fixed on main.

| Item | Site | Change | Slice |
|---|---|---|---|
| D1 | `C:_native_gate.py` ~489-509 (`inspect.signature(run_pipeline)` probe for `unified_slice_enabled`; `import inspect` at 48) | Pass the keyword. It is in `run_pipeline` (`E:execution/_pipeline.py:152`) in the pinned 0.27.0. | C-S1a |
| D2 | `except ImportError` around engine names: `C:_mask_secret.py:77`, `C:_mask_secret_guidance.py:51-76` and 140 (`_OLD_ENGINE_HEAD`, `_OLD_ENGINE_TAIL`, `OLD_ENGINE_RUN`, `OLD_ENGINE_TOKENIZE`, `OLD_ENGINE_API`), `C:api.py:151-152`, `C:cli/exit_codes.py:274,280`, `C:cli/run/_errors.py:138,150`, `C:cli/run/_prepare.py:428-429`, `C:cli/tokenize.py:306-307`, `C:cli/extras.py:192-196` (`NerUnavailableError`, `PlanCompileError`), `C:ci/engine_logging.py:28-30` (`decoy_engine.internal.logging`) | Plain imports; delete the `OLD_ENGINE_*` texts. | C-S1b |
| D3 | `getattr(decoy_engine, "native_companion_status", None)` at `C:_native_gate.py:139`, `C:cli/preflight.py:552`, `C:cli/info.py:84`, `C:distribution/selfcheck.py:47`; `hasattr(_engine_execution, "estimate_job_capacity")` at `C:cli/preflight.py:395-397` (module imported under an alias); `getattr(engine_errors, "EnvFlagError", None)` at `C:cli/exit_codes.py:233` | Plain attribute access. `selfcheck.py` keeps its `try: import decoy_engine except Exception` (`:42-44`): reporting a broken install is that command's job. | C-S1a (`exit_codes.py` site in C-S1b) |
| D4 | `C:cli/report.py` ~893 `import pandas` guard | Delete (pandas is a hard dependency). | C-S1a |
| D5 | `C:cli/run/_execute.py` ~339-352, `_report_kwargs` left out "so the default call shape stays valid on an older engine" | Pass the keywords. | C-F1a (same hot file as A9) |
| D6 | `C:cli/io/_scan_set.py` `_LEGACY_FIELD_*`, `_from_legacy`, `_legacy_field`; `C:cli/io/_targets.py` ~193 `_legacy_format_for_path` | OQ-5 (decided: delete). The remaining readers refuse an untagged or pre-`scan-set/v1` saved scan, and a manifest entry with no `format`, with a coded CLI error (`scan.saved_scan_schema_unsupported`, `io.manifest_format_missing`), exit 1, value-free. | C-S2 |
| D7 | `E:execution/out_of_core/_source.py`, a re-export of `LazySource` from `E:profile/_readers` | Move 8 src importers (`out_of_core/__init__.py`, `_preflight.py`, `_relation.py`, `_rewrite_pass.py`, `_route_policy.py`, `_runner.py`, `_stage.py`, `_stream_driver.py`) and about 16 tests; delete the module. | E-S2a |
| D8 | Re-exports in `E:execution/_mem_estimate.py` (~84-93), `_planner_columns.py` (through `_planner`), `_sequential.py:169` (`table_topo_order`), `_chunked_fk.py` (~22-35), `_pipeline_routing.py` (~22-40), `native/_dispatch.py` (`noqa: F401 -- re-exported for tests`) | Importers move to the owning module; the re-export lines go. `run_pipeline` imports the owning modules directly. | E-S2b |
| D9 | `E:quality/dp_budget.py` ~499-520, a module `__getattr__` that re-exports `OpenDpReleaseSession`, plus an empty `if TYPE_CHECKING: pass` | Delete. Update the docstrings that name the old path (`E:quality/dp.py:11`, `E:quality/dp_session.py:16`). | E-F1 |
| D10 | `E:execution/_fk_key_compat.py`, a one-line delegate to `_fk_keys.fk_key_value` | Importers (`_pandas_adapter.py:51`, `ET:unit/execution/test_pandas_adapter_helper_kills.py:14`) move; delete; drop its rows in `ET:sentry/layout/test_module_size.py` and the seam test. | E-S2a |
| D11 | `E:execution/_chunked_adapter_gate.py`: `chunked_adapter_touches_pandas_ingestion` always returns True | Fold the constant into the one caller (`_chunked_oracle.py:32`) and remove the dead branch; delete the module and its test references (`ET:unit/execution/test_de10_chunked_fk_passthrough.py:365`). | E-S2a |
| D12 | `E:context.py` `emit_step` `TypeError` retry | Goes with the emit dispatch helper. | E-S1b |
| D13 | V2 custom-provider table | Not a shim; out of scope (section 1). | none |

Optional-dependency guards that stay, and form the allowlist of the CLI import-guard sentry:
`C:_private_file.py:45` (Windows `fcntl`), `C:cli/compile_explain.py:345`, and
`C:distribution/selfcheck.py:42-44` (reports a broken install).

Failure modes: D1 to D5 rely on the exact engine pin. If the pin ever moves backwards, the plain
import fails at import time with an `ImportError` naming the module, which is the right failure.
D7, D8, D10 and D11 are private paths. A missed importer fails at import, so each E-S2 slice runs
`python -c "import decoy_engine; import decoy_engine.execution"` and the seam tests on the VM in
addition to T1.

## 5. Row 24zl PROP-GUARDS

| Item | Today | Change | Slice |
|---|---|---|---|
| E2 | Each allowlist is written up to four times: an in-code constant in the sentry, `tests/sentry/baselines/<id>.json`, a row in `scripts/dev/sentry_registry.toml`, and a `Source` in `tests/sentry/_baseline_sources.py` (engine 36 rows, 19 `in_code`; CLI 26 rows). | E-G2a adds a `kind` column to `sentry_registry.toml` and builds `SOURCES` from it, so `_baseline_sources.py` stops being a hand table. One loader, `load_allowlist(sentry_id)` in `tests/sentry/_ratchet.py`, reads the source the row names. Source per kind: `in_code` moves to the baseline JSON (the only allowlist from then on); `json_keys` and `from_file` already read a JSON file; `toml_keys` and `import_layer_keys` keep their own files (`pyproject.toml`, `.importlinter`) because those files are the configuration itself. `test_baseline_registry.py` keeps its job (every registry row has its source, every JSON has a row). The shrink-only ratchet is unchanged. Row 24ze builds on this loader. | E-G2a, E-G2b, C-G1 |
| E1 | Hand list `SENTRIES` in `tests/sentry/test_sentry_manifest.py` (engine about 106 entries, including `tests/secret_providers/test_leak_sentry.py`; CLI about 72). The test cross-checks `scripts/dev/gates.sh` `SENTRY_PATHS`, `LAYER_TEST` and `LAYER_IGNORE`. | `SENTRIES` becomes the glob `tests/sentry/**/test_*.py` plus an explicit tuple of the paths outside `tests/sentry/`. The gates.sh cross-check stays. | E-G1, C-G1 |
| E3 | `ET:sentry/test_physical_seam_disconnection.py` (1057 lines) holds `test_production_execution_modules_are_byte_identical_to_origin_main` (~296) and its ~720-line allowlist. | Delete that test and its allowlist (owner 2026-11-15). Keep the import-direction tests (~164-221 and ~1039). Update the two CODEMAP rows that describe the seam guard. `.github/workflows/ci.yml:121-128` keeps `fetch-depth: 0` (`scripts/dev/ratchet_check.py:44` needs the merge base) and its comment is rewritten to name the ratchet instead of the deleted gate. | E-G1 |
| E4 | `CT:sentry/layout/test_codemap_paths.py` pins the `KINDS` frozenset of verbatim row titles. | Drop `KINDS`; keep the path-exists test. | C-G1 |
| E6 | Baseline header pins (`doc["created_in"] ==`, `sentry_id`, registry text) in seven CLI files: `CT:sentry/cli_text/test_one_error_emitter.py`, `cli_text/test_stdout_writes.py`, `defects/test_exit_code_owner.py`, `defects/test_exception_context.py:26`, `io_policy/test_config_load_choke_point.py`, `io_policy/test_environment_reads.py`, `io_policy/test_private_files.py`. The engine has none. | Delete the header asserts; `test_baseline_registry.py` already checks every baseline header once. | C-G1 |
| E7 | `ET:sentry/test_wave_b_no_registry_version_literal.py` (obsolete since REG-RELEASE: `REGISTRY_VERSION` moves only at release); `ET:sentry/test_perf_claim_provenance.py` (a forward invariant on `docs/`). | OQ-6 (decided): delete the Wave B guard, keep the perf guard. | E-G1 |
| Comment history | No guard. | A sentry in each repo fails a new comment or docstring under `src/` that carries a task id, review round, dated decision or reviewer name. Baseline: per-file counts of today's hits in `tests/sentry/baselines/comment-history.json`, numeric `max`, shrink-only through the existing ratchet. | E-G3, C-G2 |
| K1 | `C:.github/workflows/regen-diagrams.yml` commits `docs/diagrams/{classes_decoy,deps,packages_decoy}.svg` as `github-actions[bot]` after each push to main, with `permissions: contents: write`. | Upload the three SVGs with `actions/upload-artifact`; `permissions: contents: read`; delete the committed SVGs; drop `docs/diagrams/*.svg` from `GENERATED_UNREAD_GLOBS` (`scripts/dev/gates.sh:65`) and the three entries in `CT:sentry/baselines/retired-name-pending.json` (~37-45). `CT:unit/scripts/test_gates_baseline_file.py:710-729` uses synthetic paths and stays. `C:docs/records/2026-11-08-cli-baseline-build.md` is a record and stays. | C-G2 |

Comment-history scanner:

- One pattern module, `tests/sentry/_comment_history.py`, written in the engine. The CLI vendors
  it byte for byte and pins it in `ci/vendored.toml`, as it already does for
  `tests/sentry/layout/_layout.py`. The patterns are written once.
- It reads `tokenize` `COMMENT` tokens and `ast` docstrings (module, class, function). It does
  not read other string literals, so reason texts and test data do not count.
- Patterns (case-sensitive unless marked):
  - Dated decision: an ISO date `\b20\d\d-\d\d-\d\d\b` in parentheses, or in the same comment as
    one of `owner`, `decided`, `decision`, `added`, `fixed`, `merged`, `landed`, `as of`, `per`
    (case-insensitive). An example date in a docstring (`"2024-01-15" -> "2024-03-02"`) passes.
  - Reviewer names as whole words: `\b(Dennis|Codex|Barry|Fable)\b`.
  - Review phrases: `plan-gate`, `cold-read`, `\b(review|gate) round \d+\b`, `\bround \d+
    (finding|review)\b`, `\bBLOCKER\b`.
  - Task ids: `\b(Task|Sprint|Slice|Wave) [A-Z0-9][\w.-]*` and `\b[A-Z]{1,6}-\d+[a-z]?\b`, minus
    an exclusion list of standards and code systems: `AES-\d+`, `SHA-\d+`, `UTF-\d+`,
    `RFC-?\d+`, `ISO-?\d+`, `CVE-\d+`, `GHSA-`, `PEP-?\d+`, `ICD-\d+`, `HKDF-`, `FF\d-`.
- Scope: `src/` only.

Failure modes for package E:

- E2: a sentry that loads its allowlist from JSON but skips the ratchet would accept a grown
  file. Growth is still caught by `scripts/dev/ratchet_check.py`, which compares the JSON against
  the merge base.
- E1: the glob picks up any `test_*.py` under `tests/sentry/`. Accepted: by the CODEMAP rule
  every file there is a sentry.
- E3: with the byte-identical gate gone, a production module under `execution/` could start to
  import the physical seam. The kept import-direction tests fail that, which is the property the
  owner chose to keep.
- Comment history: a false positive on a real word. The negative fixtures pin the known
  non-hits. A new false positive is fixed in the pattern module, never by an inline allow
  comment.

## 6. Design notes

- New structure: one predicate and one compile check (E-F0), one private dispatch helper (emit),
  one post-engine check function (A8b), one loader (E2), one scanner module (comment history).
  Each replaces copies or a gap; none adds a variant expected to grow.
- One place per fact: `_SPAN_DETECTORS` owns runnable regex span ids and exports its derived
  `SPAN_DETECTOR_IDS`; `NER_ENTITY_MAP` owns NER-produced ids; `DETECTOR_DEFAULTS` owns ids the
  library `extra_spans` dispatch contract supports. `SELECTABLE_TEXT_MASK_DETECTORS` and
  `TEXT_MASK_STRATEGY_DETECTORS` are derived views of those sources, and `strategy_supported`
  owns pair compatibility for dispatch and compile. The allowlist is the source its registry row
  names, and the comment patterns live in the engine module vendored by pin. Unknown target keys
  are owned only by `PipelineConfig._targets_distinct`; the CLI consumes that validation and does
  not add a second validator.
- Pattern followed: E2 copies the engine's `env_flags.FLAGS` pattern (one registry a sentry
  derives its inventory from). The E-F0 check follows `check_text_mask_ner_available` (row 30), a
  check in `plan/` wired into all three reported check lists of `_compile.py`.

## 7. Choke points and guard mutations

| Class | Choke point | Guard test | Mutation that must turn the guard red |
|---|---|---|---|
| Text-mask detector inventories (E-F0) | `_SPAN_DETECTORS`, `NER_ENTITY_MAP`, and `DETECTOR_DEFAULTS` are the sources; `SELECTABLE_TEXT_MASK_DETECTORS` and `TEXT_MASK_STRATEGY_DETECTORS` are derived in `E:transforms/text_mask.py` and read by `check_text_mask_strategies` | `ET:unit/plan/test_text_mask_strategy_check.py` proves exact derivation and distinguishes selector ids from override-only ids | Replace `SELECTABLE_TEXT_MASK_DETECTORS` with `frozenset(DETECTOR_DEFAULTS)`: AT-A1g compiles `iso_date` and `person_name` selectors and fails. |
| Detector and strategy pairs (E-F0) | `strategy_supported` in `E:transforms/text_mask.py`, read by `_mask_span` and by `check_text_mask_strategies` | `ET:unit/plan/test_text_mask_strategy_check.py`; a parity case asserts that for every (strategy-detector id, strategy) pair the check refuses exactly when `_mask_span` raises | Make `date_shift` accept any detector: AT-A1a's `ssn: date_shift` refusal goes red because it compiles. The safe parse fallback means this mutation no longer returns the real SSN. |
| Unparseable date span (E-F0) | `_mask_date_shift` | `ET:unit/transforms/test_text_mask_date_shift.py` | Return `matched_text` again: the unparseable-date case shows the input. |
| Unknown target key (A8a) | `PipelineConfig._targets_distinct`, using the target-name helper beside `duplicate_target_groups` in `E:config/_targets.py` | Engine config tests plus `CT:unit/cli_fmt/test_target_table_unknown.py`; the CLI test asserts gate location `targets.custmers` | Drop the validator call: the typo config exits 0. |
| Declared table not produced (A8b) | `missing_target_tables`, called first in both `seal_result` and `write_targets`; demo reaches it through `write_targets` | `CT:unit/cli_fmt/test_write_targets_missing_table.py` plus tokenize, API and demo caller cells | Skip the call in either writer: that writer's cell sees exit 0 and a written file. |
| Native-lane reroute (A5) | the `except` in `E:execution/_unified_slice.py` | `ET:physical/test_unified_slice_exception_boundary.py`, an intended rewrite of the current reroute assertion at `:213` | Widen the catch back to `Exception`: an injected `RuntimeError` reroutes. |
| Observation sinks (emit helpers) | one private `_dispatch_sink` in `E:context.py` | `ET:unit/test_context_emit_dispatch.py` | Delete the `except` in the helper: a raising sink fails the run. |
| Allowlist source (E2) | `load_allowlist` in `tests/sentry/_ratchet.py` (both repos) | new case `test_no_sentry_holds_an_inline_allowlist` in `tests/sentry/test_baseline_registry.py`: an AST walk of `tests/sentry/**` for a module-level `Assign` or `AnnAssign` whose value is a `frozenset`, `set`, `tuple`, `list` or `dict` literal or constructor call, in a module that a registry row of kind `in_code` named before E2 | Re-add `_ALLOWED: dict[str, str] = {...}` to one migrated sentry: the case fails. |
| Comment history | `tests/sentry/_comment_history.py` | `tests/sentry/defects/test_comment_history.py` (both repos) | Drop the reviewer-name pattern: the positive fixture `# per Dennis` no longer fails and the self-test goes red. |
| CLI engine-import probes (D1 to D3) | the exact pin in `pyproject.toml` | `CT:sentry/defects/test_engine_import_guards.py`: an AST walk of `src/` that fails (1) a `try` whose body imports a `decoy_engine` module (any alias) and whose handler catches `ImportError`, `ModuleNotFoundError`, `Exception` or a tuple holding one of them, (2) `getattr` or `hasattr` with a string constant on a name bound to a `decoy_engine` module, including an aliased import such as `import decoy_engine.execution as _engine_execution`, (3) `inspect.signature` applied to a name imported from `decoy_engine`. Allowlist JSON: the three sites listed under section 4. | Re-add `hasattr(_engine_execution, "estimate_job_capacity")` in `preflight.py`: the walk fails. |
| Re-export and delegate engine modules (D7, D8, D10, D11) | the walk itself | `ET:sentry/layout/test_no_reexport_modules.py`: an AST walk of `src/` fails a non-`__init__` module (outside `PUBLIC_BOUNDARY_FILES`) whose body is only imports plus `__all__`; an import line marked `noqa: F401` whose comment says "re-export"; or a module whose only function bodies are a single `return` of a call to an imported name with the same arguments (a delegate) | Re-create `_fk_key_compat.py` with its one-line `_fk_key_value` delegate: the walk fails. |

Each walk is shown to see a seeded violation in a scratch copy before its count is trusted.

## 8. Acceptance tests (fail before, pass after)

Each test is written first and must fail on the base commit named in the header, except where the
row says it pins a no-regression fact.

| Id | Test | Fails before because |
|---|---|---|
| AT-A1a | Compile `text_mask` with `per_detector_strategy` set to each of `{ssn: date_shift}`, `{email: date_shift}`, `{email: fpe}`, `{email: faker}`: `PlanCompileError` with `config.mask.text_mask_strategy_unsupported`, the detector id and strategy in the message, and a marker cell value absent from `str(exc)`, `exc.args`, `__cause__` and `__context__`. Run the same configs on base: the `date_shift` cells' outputs contain the real SSN and email. | Compiles; `ssn: date_shift` and `email: date_shift` write the real value. |
| AT-A1b | `{person_name: fakr}`: `text_mask_strategy_unsupported`. | Compiles; the span becomes the token. |
| AT-A1c | `detectors: [emial]` and `per_detector_strategy: {emial: redact}`: `config.mask.text_mask_detector_unknown`. | Skipped silently. |
| AT-A1d | Parametrize selectors over `SELECTABLE_TEXT_MASK_DETECTORS` and override keys over `TEXT_MASK_STRATEGY_DETECTORS`. Every selector id compiles, every override-only id is refused when moved into `detectors:`, and every pair `strategy_supported` accepts compiles as an override. Direct `mask_cell_with_spans` and native `mask_cell_hybrid` calls inject supported spans and report more than zero calls through each of `fpe`, `faker` and `date_shift`; those direct calls are the source of the faker and date-shift counts. Route cells do not claim those two strategies: after E-F0, config cannot send faker or date-shift spans to native chunked, out-of-core native or SEQ because NER declines native, no built-in date detector exists, and those routes accept no `extra_spans`. | The base collapses selector and override inventories, so override-only ids compile in `detectors:`. The direct kernel counts keep the strategy coverage non-vacuous. |
| AT-A1e | Direct `_mask_span` with an unsupported pair raises tagged `ConfigError` (bypassing compile), maps to CLI exit 1, and a marker value is absent from `str(exc)`, `exc.args`, `exc.__cause__` and `exc.__context__`; `_mask_date_shift` on an injected `iso_date` span `2024-02-30` returns the token. | Returns the token for the unknown strategy and the real text for the bad date. |
| AT-A1f | Before editing fixtures, run `rg -n -U 'detectors_unknown_noop|per_detector[^\n]*(ssn|email|us_phone)[^\n]*(faker|date_shift)|strategy_map[^\n]*email[^\n]*faker|"(email|ssn)"\s*:\s*"(faker|date_shift)"' tests/` and classify every hit with `strategy_supported`; the changed-file list must equal the grep's refused-pair and unknown-id hits. It includes `tests/parity/test_c6b_ii_text_mask_seq.py`, `tests/parity/test_ooc_text_mask_native.py`, `tests/native/test_c6b_i_text_mask_chunked.py`, `tests/native/test_c6b_ii_b_text_mask_splice.py:224-225`, `tests/native/test_c6b_ii_a_text_mask_detection.py:145-147` (not `tests/parity/`), `tests/unit/transforms/test_text_mask_faker_reuse.py:140`, and `tests/native/_c6b_i_support.py:67,80`. Refused `ssn: faker`, `email: faker`, `us_phone: faker` and `ssn: date_shift` fixtures become supported direct `person_name: faker` or `iso_date: date_shift` spans where kernel coverage is intended; `detectors: [no_such_detector]` becomes an explicit refusal test. Each direct replacement asserts its faker or date-shift call count is above zero. | On base the old fixtures pass; after E-F0 they would fail compile. This row pins that every matching test fixture anywhere under `tests/` is classified and coverage is moved, not dropped. |
| AT-A1g | Compile separate configs with `detectors: [iso_date]` and `detectors: [person_name]`. Both raise `PlanCompileError` with `config.mask.text_mask_detector_unknown`; the same ids remain accepted as keys in a supported `per_detector_strategy` pair. Apply the named mutation `SELECTABLE_TEXT_MASK_DETECTORS = frozenset(DETECTOR_DEFAULTS)` and rerun this cell; both invalid selectors compile, so the mutation is red. | Both selector configs compile, but `iter_spans` skips them because neither id is a key of `_SPAN_DETECTORS`; the default unmatched policy redacts the whole cell and passthrough leaves it unchanged. |
| AT-A2 | Monkeypatch `load_table` to raise `FileNotFoundError`: `geo_generalize` with the state fallback raises it. | Returns `""` states with a warning. |
| AT-A3, A4, A6 | No behavior test (unreachable). An ordering test, `ET:unit/plan/test_compile_check_order.py`, pins that `check_unknown_provider` runs before `_build_seed_envelope` and `_check_parse_rules` before `_check_forward_references`. | Passes before; it pins why each catch is dead. |
| AT-A5 | Inject a `RuntimeError` into `reconstruct_source_shaped_output`: `run_pipeline` raises it, and no `_REROUTE_LOG` record is emitted. | Reroutes and returns success. |
| AT-A5b | In `ET:physical/test_unified_slice_exception_boundary.py`, error parity covers FPE sub-floor with no `sub_floor_span`, checksum failure, a `when:` expression error, the E-F0 `_mask_span` `ConfigError`, validator failure, and provider failure. For each, unified-slice on and `unified_slice_enabled=False` raise the same raw exception type, reason code and CLI exit code; the E-F0 execution cell matches the oracle's wrapped `StrategyError`, exit 3, rather than exposing the direct helper's `ConfigError`. | On base the lane catches and reroutes, so the pandas rerun raises; the rewrite pins that removing the catch preserves the oracle boundary rather than exposing a lower-level type. |
| AT-A7 | Set `sys.modules["decoy_engine.config"] = None` (so the import raises `ImportError`) and call `_validate_scaffold`: the `ImportError` propagates. | Returns silently. |
| AT-A8a | Engine config with a `targets:` key `custmers` and a source of that name but no table: `PipelineConfig` refuses it with `config.target_table_unknown`. Through the repinned CLI, `decoy run` and `decoy validate` exit 1 before any source read and locate the gate finding at `targets.custmers`, not `.format`. | Exits 0, no file. |
| AT-A8b | Route matrix (section 2.4): for each run route, a two-table config, then the engine result with one table removed; `seal_result` raises `io.target_table_missing`, exit 3, and neither file is written. Separate cells call the retained `_write_mask_outputs` path through `cli/tokenize.py` and `api.py`, and the wrapper in `cli/demo.py`; each raises the same error before either target is written. A chunked run whose tables were engine-written still exits 0. | Each old writer skips the missing table, writes the other file and exits 0. |
| AT-A9 | The run summary for a golden config is unchanged after the deletion. | Passes before; pins no regression. |
| AT-B | `ET:unit/test_public_api.py` lists the reduced `__all__`; `test_frozen_surface_map.py` passes with the edited page; `hasattr(decoy_engine, "BundlePool")` is False. | `__all__` holds the names. |
| AT-B7 | `test_r3_public_signature_freeze.py` pins the signature without the four keywords; `docs/compatibility-contract.md` states the new count. | The signature has them. |
| AT-D | `test_no_reexport_modules.py` (section 7). | `_source.py`, `_fk_key_compat.py` and the D8 lines exist. |
| AT-C-D | `test_engine_import_guards.py` (section 7). | 13 guarded imports and 7 probes exist. |
| AT-D6 | A saved scan without the `scan-set/v1` tag, and a manifest entry with no `format`: each exits 1 with its code, value-free. | Read through the legacy readers. |
| AT-E1 | Add an empty `tests/sentry/test_zz_probe.py` in a scratch copy: the manifest test passes with no list edit. | The manifest fails until the list is edited. |
| AT-E2 | `test_no_sentry_holds_an_inline_allowlist` (section 7). | 19 engine sentries and the CLI `InCode` sentries hold inline constants. |
| AT-E3 | The seam test file runs no `git show origin/main:`; the import-direction tests still fail when a fixture module under `execution/` imports `execution.physical`. | It calls git and compares bytes. |
| AT-E4, E6 | Rename a CODEMAP row title in a scratch copy: `test_codemap_paths` passes. Change one baseline's `created_in`: only `test_baseline_registry` reacts. | `KINDS` and the seven header asserts fail. |
| AT-CH | Positive fixtures (one per pattern family) fail the scanner. Negative fixtures pass: `AES-256`, `UTF-8`, `SHA-256`, `RFC 3339`, `ICD-10`, `Argon2`, `HKDF-SHA256`, "round to 2 decimal places", an example date in a date-shift docstring (`"2024-01-15" -> "2024-03-02"`), a date inside a string literal. The real tree passes against the committed baseline. Adding `# per Dennis round 2` to a src file fails. | No scanner exists. |
| AT-K1 | `CT:sentry/tooling/test_no_bot_commits.py`: no workflow step runs `git commit` or `git push`, and `docs/diagrams/*.svg` is not tracked. It does not check `permissions:`, so a release workflow that needs `contents: write` to publish (row 93) is not blocked. | `regen-diagrams.yml` commits and pushes. |

## 8a. Class table (recurring defect classes)

| # | Class | How this batch handles it | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | E-F0 closes a live value leak: `date_shift` on a non-date detector and on an unparseable date returned the real text. All new refusals (E-F0 codes, A8a, A8b, D6) name the column, detector id, strategy, table name or path only. | AT-A1a (real value on base, marker absent from the error after), AT-A1e, AT-A8a, AT-A8b. | Return `matched_text` in `_mask_date_shift`: AT-A1e fails. Format a sample row into the A8b message: its marker check fails. |
| 2 | Cleanup missing on an exit path | A8a refuses before any read; A8b refuses before the first write, so no staged file is left. | AT-A8a and AT-A8b assert the target directory holds no new file. | Move the A8b check after the first write: one file remains. |
| 3 | State machine and concurrency | N/A: no state or thread is added. The emit dispatch helper keeps today's swallow rule. | | |
| 4 | Route parity and silent fallback | The batch's main class. The E-F0 check runs at compile, before route choice, so every route sees the same refusal. It also distinguishes built-in selector ids from override-only ids before `iter_spans` can skip the latter. Direct `mask_cell_with_spans` and `mask_cell_hybrid` cells cover the otherwise unreachable faker and date-shift kernel branches. A5 removes a silent route switch. A8b is proved per engine route and per retained CLI writer. | AT-A1a; AT-A1g; direct AT-A1d kernel cells; AT-A1f fixture inventory; AT-A5, AT-A5b; AT-A8b route and writer matrix. | Replace the selector inventory with all `DETECTOR_DEFAULTS` keys: AT-A1g fails. Wire the check into only one check list: the `decoy validate` cell of AT-A1c fails. Widen the A5 catch: AT-A5 fails. |
| 5 | Referential integrity | N/A: no key, FK or join behavior changes. The FK dtype catches are kept (section 1). | | |
| 6 | Untrusted producer | The config is the untrusted input for E-F0 and A8a; each is validated once by engine compilation or `PipelineConfig`. Inside, `_mask_span` raises on a pair the compile check should have refused. | AT-A1b, AT-A1c, AT-A1e, AT-A1g, AT-A8a. | Drop the predicate call in `_mask_span`: AT-A1e fails. |
| 7 | TOCTOU on a path | N/A: A8b reads the in-memory outputs and the sink's engine-written set, not the file system. | | |
| 8 | Weak tests and overclaimed evidence | Each acceptance test is labeled fail-before or no-regression pin. AT-A1d now fails on the base inventory collapse and requires non-zero span counts per strategy. AT-A1g names the realistic inventory mutation. AT-A1f, AT-A3/A4/A6, AT-A5b and AT-A9 state their exact role. The A5 flight is void with zero activations. Every new walk is shown red on a seeded violation. | The builder records the base-commit result of each fail-before test in the PR body. | Remove the span-count assertion from AT-A1d: the faker branch can go uncovered unnoticed. Restore `frozenset(DETECTOR_DEFAULTS)` as the selector set: AT-A1g fails. |
| 9 | Refactor drift | The D shim deletions and the emit helper collapse must not change behavior. D11 folds an always-true predicate, so the oracle branch it guarded runs as today. | Existing unit and parity tests for each moved importer stay green on T1; AT-D; `test_context_emit_dispatch.py` asserts each `emit_*` still calls the matching logger method once and a raising method does not fail the run. | Make D11's folded constant False: the chunked oracle tests fail. Swap two method names in the dispatch: the emit test fails. |
| 10 | Frozen contract drift | B1 to B8 and D9 remove public names on purpose, recorded in `docs/frozen-surfaces.md`, `docs/compatibility-contract.md`, `test_public_api.py`, the r3 signature freeze and `CHANGELOG.md` in the same slice. The plan YAML `checks_passed` list changes for every config and its three pin sites move. Reason codes are append-only: `fk.self_reference` stays; the engine adds the two E-F0 codes and `config.target_table_unknown`; the CLI adds `io.target_table_missing`, `scan.saved_scan_schema_unsupported`, `io.manifest_format_missing`. | AT-B, AT-B7, E-F0 plan YAML pins, `test_frozen_surface_map.py`, `test_reason_registry.py`, `test_reason_baseline_frozen`. | Remove a name from `__all__` without editing the page: `test_frozen_surface_map.py` fails. Delete `fk.self_reference` with the alias: `test_reason_registry.py` fails. |

## 8b. Enumerations (from the code at the bases)

### Routes

- Text mask runs on the full-frame strategy (`E:execution/_strategies/_text_mask.py:100`), the
  out-of-core group C path (`E:execution/out_of_core/_mask_group_c.py:259`), the out-of-core
  native path (`E:execution/out_of_core/_text_mask_native.py:75`) and the native operator path
  (`E:execution/native/_operator_params.py:243`), whose FPE eligibility is derived from
  `_FPE_CONFIG` (`E:execution/native/_text_mask_native_fpe.py:41-49`). E-F0 validates
  `detectors:` against the exact built-in selector inventory at compile, before route choice, so
  all four routes refuse `iso_date`, `person_name`, and every other non-runnable selector. After
  that refusal, config cannot make faker or date-shift spans reach native chunked, out-of-core
  native or SEQ: NER declines native, no built-in date detector exists, and the route APIs accept
  no `extra_spans`. Direct `mask_cell_with_spans` and `mask_cell_hybrid` cells cover those kernels.
- A5 is the unified-slice route only (`E:execution/_unified_slice.py:359`).
- A8b: the engine routes in section 2.4.

### Exit paths

- E-F0 compile refusals, A8a and D6: a coded config error, CLI exit 1, at compile or config check
  and in `decoy validate`. A direct caller that bypasses compile gets tagged `ConfigError`,
  CLI exit 1; execution routes expose the oracle's wrapped `StrategyError`, exit 3.
- A2, A5, A6, A7: the original exception propagates; CLI exit 3 (runtime).
- A8b: `TargetTableMissingError`, exit 3, before any write.
- Emit helpers: no exit change; a raising logger method is swallowed and logged at DEBUG.

### FK shapes

- N/A: no FK behavior changes.

### Fields (every key this plan adds or reads)

- No config key is added. E-F0 validates the existing `detectors` list and the keys and values of
  `per_detector_strategy`. A8a validates the keys of the existing `targets` map.
- No result or report field is added. `checks_passed` is an existing field, but E-F0 appends one
  item to it and therefore changes serialized plan YAML for every config.

### Output surfaces

- Masked output bytes: unchanged for every parseable span of every config that compiles after
  E-F0 and uses a runnable selector. An unparseable date-like span becomes the token instead of
  the real text. A config that selected a library-only id such as `iso_date` or `person_name` no
  longer produces the base's whole-cell redaction or passthrough output because it is refused at
  compile.
- Files on disk: A8a and A8b now refuse runs that exited 0 with a missing file; neither writes a
  partial set.
- Logs: A5 removes the `_REROUTE_LOG` line for non-coded exceptions; A2 removes one warning.
- Public API: the B and D9 removals. E-F0 adds only the public-in-package
  `detection.detectors.SPAN_DETECTOR_IDS` derived view; it is not exported from the engine root.

### Lists

- Strategy names: `fpe`, `faker`, `date_shift`, `redact`, `passthrough`.
- Selector inventory: `SELECTABLE_TEXT_MASK_DETECTORS`, derived exactly from
  `SPAN_DETECTOR_IDS`, which is derived from `_SPAN_DETECTORS` keys.
- Per-detector strategy-key inventory: `TEXT_MASK_STRATEGY_DETECTORS`, derived from the selector
  inventory, `NER_ENTITY_MAP` values, and `DETECTOR_DEFAULTS` keys. `DETECTOR_DEFAULTS` is the
  existing source for ids accepted from the library `extra_spans` API.
- `_FAKER_METHOD` keys: `person_name`, `first_name`, `last_name`, `address`, `location`.
- `_FPE_CONFIG` keys: `ssn`, `us_phone`, `us_zip`, `pan`, `fax_number`, `npi`.
- Date detectors: `iso_date`, `us_date`, `eu_date`.
- `write_targets` callers: `C:cli/run/_execute.py` `_write_mask_outputs` (itself called from
  `C:api.py:633` and `C:cli/tokenize.py:371`) and `C:cli/demo.py:295` `_write_mask_outputs`.
  DELIV C2a keeps the tokenize and API old path until C4; demo remains separate. RUN-STREAM C1a
  adds `seal_result` for run routes. `missing_target_tables` is shared by `seal_result` and
  `write_targets`, and demo reaches it through `write_targets`.
- `emit_*` helpers: `emit_step`, `emit_lineage`, `emit_fidelity`, `emit_quarantine`,
  `emit_throughput_sample`. Three remain after B5.
- CLI engine-import guards: the D2 sites (13 imports in 9 files) and the D3 probes (7 sites);
  three allowlisted sites stay (section 4).
- Engine sentry baselines: 36 registry rows (19 `in_code`, 5 `json_keys`, the rest other kinds);
  CLI: 26 rows.

## 8c. Reuse inventory and frozen contracts

- Reuse: `_SPAN_DETECTORS`, `NER_ENTITY_MAP`, and `DETECTOR_DEFAULTS` as the three existing
  detector-id sources; the `plan/_compile.py` check lists that already carry
  `check_text_mask_ner_available`;
  the engine's `PipelineConfig._targets_distinct` validator and `duplicate_target_groups` helper;
  the ratchet and
  `test_baseline_registry.py` in both repos; the CLI vendoring pin `ci/vendored.toml`;
  `scripts/test_flight.py` for OQ-3.
- Frozen contracts touched: `decoy_engine.__all__` and `docs/frozen-surfaces.md` (B1, B2, B4,
  B5, B6, B8 removals, and D9 in E-F1); the `run_pipeline` signature and `docs/compatibility-contract.md`
  (B7); the serialized plan YAML `checks_passed` list; the engine reason registry (three added
  codes); the CLI reason registry (three added codes);
  CLI exit codes (A8a moves a typo config from exit 0 to exit 1, A8b moves a missing-table run from
  exit 0 to exit 3); report tags (D6 drops the pre-`scan-set/v1` reader). The JSON result schemas
  change is documented and pinned. Masking output remains identical for every parseable span of
  every config that still compiles.

## 8d. Pre-mortem

| Risk | Guard |
|---|---|
| E-F0 refuses a pairing users rely on (for example `faker` on `us_phone`) | OQ-2 is decided; the release notes name each refusal and list the supported pairs; `docs/strategies.md` lists them too. |
| E-F0 fixture moves drop faker or date-shift kernel coverage | AT-A1f inventories every refused fixture; direct `mask_cell_with_spans` and `mask_cell_hybrid` AT-A1d cells require non-zero calls. |
| A5 turns a rare native exception into failed customer runs | The OQ-3 flight with a counted instrument and a non-zero activation count; E-F2 can ship after the E-F0 daily train. |
| A8b fires on a route that legitimately streams a table | The check counts the engine-written set; AT-A8b covers each route. |
| A8b lands before its choke point exists | C-F1b waits for DELIV C2a and RUN-STREAM C1a (section 10). |
| A removed public name has an unseen outside user | Pre-GA rule; the platform was checked; the 0.29.0 notes list every removal. |
| A deleted shim still has an importer in a test outside T1 selection | Each E-S2 slice runs the import smoke and the full suite (moved or deleted tests are an escalation trigger). |
| The E2 move loosens a sentry by loading the wrong source | `test_baseline_registry.py` checks each row's source; each migrated sentry keeps its seeded-violation self-test. |
| The comment guard blocks normal work on false positives | Negative fixtures; the baseline holds today's hits; fixes go in the pattern module. |

## 9. Placement

Checked against the engine and CLI CODEMAP "Where Things Go".

| New or moved thing | Path | CODEMAP row | Beside |
|---|---|---|---|
| `SPAN_DETECTOR_IDS` | `E:detection/detectors.py`, derived from `_SPAN_DETECTORS` | Detectors, profiling | `_SPAN_DETECTORS` |
| `strategy_supported`, `SELECTABLE_TEXT_MASK_DETECTORS`, `TEXT_MASK_STRATEGY_DETECTORS` | `E:transforms/text_mask.py` | transforms (owning module) | `DETECTOR_DEFAULTS`, `_FAKER_METHOD`, `_FPE_CONFIG` |
| E-F0 compile check | `E:plan/checks/_text_mask_strategy.py` | plan checks | `plan/checks/_generate_columns.py` |
| E-F0 reason codes | `E:reasons/config/` (the part file that holds `mask.*` codes) | reason registry | `MASK_UNKNOWN_STRATEGY` |
| E-F0 tests | `ET:unit/plan/test_text_mask_strategy_check.py`, `ET:unit/transforms/test_text_mask_date_shift.py`, and existing native/parity files from AT-A1f | unit tests for the owning surface plus named existing route suites | existing `plan`, `transforms`, native and parity tests |
| A5 tests | `ET:physical/test_unified_slice_exception_boundary.py` | Physical seam tests, CODEMAP row 256 | the existing test rewritten at line 213 |
| Emit dispatch helper | private function in `E:context.py` | Public API (private helper in a public module) | the `emit_*` functions |
| A8a validator and code | target-name helper in `E:config/_targets.py`, called by `PipelineConfig._targets_distinct` in `E:config/_pipeline.py`; `config.target_table_unknown` in the engine reason registry | Config models, engine CODEMAP row 247 | `duplicate_target_groups` and `TARGET_SHARED_DESTINATION` |
| A8b check and error | `missing_target_tables` and `TargetTableMissingError` in `C:cli/io/_targets.py`; `io.target_table_missing` in the CLI reason registry | same | `write_targets` |
| A8 tests | `CT:unit/cli_fmt/test_target_table_unknown.py`, `CT:unit/cli_fmt/test_write_targets_missing_table.py` | `tests/unit/cli_fmt/` | other target tests |
| D6 codes | CLI reason registry | same as its `scan.*` and `io.*` codes | |
| Allowlist loader | `load_allowlist` in `tests/sentry/_ratchet.py` (both repos) | Sentry test (`tests/sentry/_ratchet.py`) | the ratchet functions |
| Comment-history pattern module | engine `tests/sentry/_comment_history.py`; CLI vendored copy at the same path, pinned in `ci/vendored.toml` | Sentry test helper; CLI vendored pin | `_ratchet.py` |
| Comment-history sentry | `tests/sentry/defects/test_comment_history.py` (both repos); baseline `tests/sentry/baselines/comment-history.json`; one registry row each | recurring-defect class rules in `tests/sentry/defects/` | other `defects/` sentries |
| Engine-import-guard sentry | `CT:sentry/defects/test_engine_import_guards.py`; baseline `CT:sentry/baselines/engine-import-guards.json` | same | same |
| Re-export sentry | `ET:sentry/layout/test_no_reexport_modules.py` | layout fitness functions | `test_module_size.py` |
| Bot-commit sentry | `CT:sentry/tooling/test_no_bot_commits.py` | test tooling rules | other `tooling/` sentries |

Every new element has a present consumer in the same slice; no slice merges a helper for a later
slice.

`E:transforms/text_mask.py` is 650 lines at the base and pinned at 670 by
`ET:sentry/test_module_size.py:143`. E-F0 deletes the inner Faker fallback and both FPE lookup
defaults before adding the predicate and guard, and the finished file must stay at or below 670.
The ceiling is never raised. `transforms/` already has 26 direct entries and its CODEMAP says the
next module requires a named sub-package, so E-F0 adds no sibling transform module merely to evade
the cap. `E:detection/detectors.py` is pre-existing oversize code; adding only the derived
`SPAN_DETECTOR_IDS` beside its owning map is a `V2-LOG` size follow-up, not a change-created design
blocker. E-F0 does not add a module or another detector list.

## 10. Slices

Production files exclude tests, baselines, docs and CI YAML. Each slice stays at or under 10
production files and 800 changed lines; a slice that grows past either splits at the boundary its
row names.

| Slice | Repo | Items | Prod files (est.) | Lines (est.) | Risk | Depends on |
|---|---|---|---|---|---|---|
| E-F0 | engine | Section 2.1 (leak fix, two derived detector inventories, predicate, compile check, detector-id refusal, runtime error boundary, draw-site wording and pin), AT-A1d and AT-A1g inventory and direct-kernel cells, AT-A1f fixture moves, plan YAML pins, changelog, `docs/strategies.md` | 9 (`detection/detectors.py`, `transforms/text_mask.py`, `_strategies/_text_mask.py`, `native/_text_mask_native_fpe.py`, `native/_draw_sites_mask.py`, `out_of_core/_mask_group_c.py`, new `plan/checks/_text_mask_strategy.py`, `plan/_compile.py`, the `reasons/config` part file) | <=800 total changed lines, currently estimated ~680 including tests and docs | R2 (live value leak; wrong output from accepted non-runnable selectors; output and serialized-plan change; new compile refusal) | none; first in the batch; `text_mask.py` stays at or below its 670-line pin without raising it; split before review if either cap is exceeded |
| E-F0 release | engine | Daily train containing E-F0 alone; changelog names the masking refusal, safe date fallback and plan YAML `checks_passed` addition | | | R2 | E-F0 |
| E-F0 repin | CLI | Pin the E-F0 engine release before any surface-lane release | | | R1 | E-F0 release |
| E-G1 | engine | E3, E1, E7, `ci.yml` comment | 0 | -800 / +80 | R1 | none |
| E-G2a | engine | E2 `kind` column, registry-derived `SOURCES`, loader, first half of the `in_code` sentries | 0 | ~600 | R1 | E-G1 |
| E-G2b | engine | E2 remaining sentries, `test_no_sentry_holds_an_inline_allowlist` | 0 | ~500 | R1 | E-G2a |
| E-G3 | engine | comment-history guard, pattern module, baseline | 0 | ~400 | R1 | E-G2b |
| E-F1 | engine | A2, A3, A4, A6, A8a, D9 | 10 (`transforms/geo_generalize.py`, `plan/_seed_envelope.py`, `plan/checks/_generate_columns.py`, `execution/physical/_compiler.py`, `quality/dp_budget.py`, `quality/dp.py`, `quality/dp_session.py`, `config/_targets.py`, `config/_pipeline.py`, engine reason registry) | ~300 | R2 (D9 removes an old public import path; A8a adds a config refusal) | E-G1 |
| E-F2 | engine | A5 | 1 | ~150 | R2 (a native-lane exception now fails the run) | E-G1; OQ-3 flight evidence |
| E-S1a | engine | B1, B2, B4, B6, B8 | 8 (`__init__.py`, `internal/crypto.py`, `context.py`, `execution/_events.py` deleted, `execution/__init__.py`, `validation_result.py`, `_progress_events.py`, `progress.py`) | ~280 | R2 (public API) | none |
| E-S2a | engine | D7, D10, D11, re-export sentry | 10 (8 `out_of_core` importers, `_pandas_adapter.py`, `_chunked_oracle.py`; 3 modules deleted) | ~250 | R1 (private paths) | E-G1 |
| E-S2b | engine | D8 | up to 10 (`_mem_estimate.py`, `_planner.py`, `_sequential.py`, `_chunked_fk.py`, `_pipeline_routing.py`, `native/_dispatch.py`, the importers that move) | ~300 | R1 | E-S2a |
| E-S1b | engine | B3, B5, B7, D12, emit dispatch helper | up to 9 (`context.py`, `execution/_pipeline.py`, and the files that carry `stream_chunked_output`, `progress_interval_s`, `secret_registry`, `secret_cache_policy`) | ~400 | R2 (public API, `run_pipeline` signature) | E-S1a (`context.py`), E-S2a (`_chunked_oracle.py`), E-S2b (`_pipeline.py` area); split by keyword if over 10 files |
| Surface release | engine | 0.29.0; notes list every removed name (D9 included), A8a, and the remaining refusals | | | | E-F1, E-S1a, E-S1b; E-F2 if merged by then, else the next train |
| Surface repin | CLI | pin `decoy-engine==0.29.0` (engine repin checklist) | | | R1 | Surface release |
| C-G1 | CLI | E2, E1, E4, E6 | 0 | ~600 | R1 | none; split E2 from E1/E4/E6 if over 800 |
| C-G2 | CLI | comment-history guard (vendored module), K1, bot-commit sentry | 0 (workflow YAML, SVG deletions) | ~300 | R1 | C-G1; E-G3 merged (vendored source) |
| C-S1a | CLI | D1, D3 (except `exit_codes.py`), D4 | 5 (`_native_gate.py`, `cli/preflight.py`, `cli/info.py`, `distribution/selfcheck.py`, `cli/report.py`) | ~150 | R1 | none (0.27.0 ships every name) |
| C-S1b | CLI | D2, D3 `exit_codes.py` site, engine-import-guard sentry | 9 (`_mask_secret.py`, `_mask_secret_guidance.py`, `api.py`, `cli/exit_codes.py`, `cli/run/_errors.py`, `cli/run/_prepare.py`, `cli/tokenize.py`, `cli/extras.py`, `ci/engine_logging.py`) | ~350 | R1 | C-S1a (the sentry's allowlist holds only the three kept sites) |
| C-S2 | CLI | D6 | 2 (`cli/io/_scan_set.py`, `cli/io/_targets.py`) plus the reason registry module | ~200 | R1 | none |
| C-F1a | CLI | A7, A8a acceptance and gate-location pin, A9, D5 | 4 (`cli/init.py`, `cli/gate/_layers.py` only if location rendering needs a fix, `cli/run/_render.py`, `cli/run/_execute.py`) | ~180 | R2 (exit code change on a config that exits 0 today) | Surface repin; the open row 63a RUN-STREAM CLI slices (C1l, C1a, C1b) that edit `_execute.py` and `_render.py` merge first |
| C-F1b | CLI | A8b | 3 (`cli/io/_targets.py`, the module holding `seal_result`, CLI reason registry module) | ~200 | R2 (exit code change) | row 61 DELIV C2a and row 63a RUN-STREAM C1a merged; the section 2.4 amendments applied to both plans |

Ordering:

- E-F0, its own daily engine release and its CLI repin land first. Only then does E-G1 start, so
  the live leak ships ahead of the surface lane and later `execution/` slices stop editing the
  720-line allowlist.
- After E-G1 the lanes run in parallel in separate worktrees: guard lane E-G2a, E-G2b, E-G3; fix
  lane E-F1, E-F2; surface lane E-S1a, E-S2a, E-S2b, E-S1b in that order. The surface lane is
  serial because `context.py` (E-S1a, E-S1b), `_chunked_oracle.py` (E-S2a, E-S1b) and
  `execution/_pipeline.py` and its routing modules (E-S2b, E-S1b) overlap.
- CLI lanes do not wait for the engine except C-G2 (vendored module), E-F0 repin, Surface repin,
  and C-F1a's A8a acceptance. C-F1a also waits on row 63a; C-F1b waits on rows 61 and 63a.
- Row 24zj merges before row 93 (REL-GATE). Row 24ze plans on top of E-G2b and C-G1.

Expected size: 18 build slices plus two engine releases and two CLI repins, so 22 PRs. Production
code is net negative; the B, D and E deletions remove about 2,500 lines, most of them the E3 allowlist and
the shims. New root public names: none. New public-in-package name: `SPAN_DETECTOR_IDS` in
`detection.detectors`. New private names: `strategy_supported`,
`SELECTABLE_TEXT_MASK_DETECTORS`, `TEXT_MASK_STRATEGY_DETECTORS`,
`check_text_mask_strategies`, `_dispatch_sink`, `_REROUTABLE` (only if a coded decline exists),
`missing_target_tables`, `TargetTableMissingError`, `load_allowlist`. New reason codes: engine
`config.mask.text_mask_strategy_unsupported`,
`config.mask.text_mask_detector_unknown`, `config.target_table_unknown`; CLI
`io.target_table_missing`, `scan.saved_scan_schema_unsupported`, `io.manifest_format_missing`.

Testing per slice (owner test-depth rule): T0 per edit, T1 impact selection per commit, gates run
T1 on the exact head. Full suite only on an escalation trigger: E-S1a, E-S1b and E-F1 (frozen
contract), E-G1, E-G2a, E-G2b and C-G1 (shared test machinery and moved or deleted tests), E-F0
(golden output and moved parity fixtures). All runs on the Mac or a VM through `~/bin/vm-run`,
never on the devbox. Mutation testing only on the E-F0 predicate and check and the A8b check (core
logic).

## 11. Established solutions

- The R2 slices (E-F0, E-F1, E-F2, E-S1a, E-S1b, C-F1a, C-F1b) add no parser, scheduler, protocol or
  method. E-F0 is a validation at an existing compile check list plus a closed lookup over
  existing tables; the rest delete catches or names. The patterns followed are in the codebase:
  `check_text_mask_ner_available` for the compile check, the frozen-surface update steps in
  `docs/frozen-surfaces.md` for removals.
- E2 follows the engine's `env_flags.FLAGS` registry pattern; no library needed.
- Comment scanning uses the standard library `tokenize` and `ast`. Ruff (the linter both repos
  run) has no rule that matches comment text against a project pattern list, so a small scanner
  is needed.
- K1: `actions/upload-artifact` is the standard way to publish CI build output.

## 12. Owner questions (decided 2026-11-16 as recommended; OQ-7 restated)

- OQ-1. Scope split: do all nine A items in this batch, although the CLI post-1.0 plan (#284)
  lists A2, A5, A6, A7 and A9 as 1.x patch. Decided: yes. E-F0 (the leak) is V1 under any reading.
- OQ-2. Refuse at compile every detector and strategy pair the code cannot carry out, unknown
  strategy names and unknown detector ids. For `detectors:`, "carry out" means exactly a key of
  `_SPAN_DETECTORS`; the broader derived inventory remains available only to
  `per_detector_strategy` and library-injected spans. Decided: yes, with the two new codes of
  section 2.1.
- OQ-3. Let an unexpected native-lane exception fail the run instead of rerunning on pandas.
  Decided: yes, after the section 2.3 flight shows no reroute from a non-coded exception with a
  non-zero activation count.
- OQ-4. Keep `use_byte_estimate_routing` and `use_probe_routing` as documented rollback switches.
  Decided: keep.
- OQ-5. Delete the pre-`scan-set/v1` and pre-CLI-FMT readers. Decided: yes, with coded refusals.
- OQ-6. Delete the Wave B guard, keep the perf-claim guard. Decided: yes.
- OQ-7 (changed by review finding H2). A target key that names no table is a config error: exit 1
  at config time (A8a). A declared table that the engine did not produce is a runtime failure:
  exit 3 at the post-engine choke point (A8b). Decided: yes to both.

## 13. Follow-ups outside this batch

- The memory note on the physical-seam sentry allowlist is out of date once E-G1 merges; the
  orchestrator updates it.
- D13 goes to the post-1.0 plan as a duplication item.
- The post-1.0 plan rows for B1 to B8, D6, D9 and A1 to A9 are marked done as each slice merges.
- The section 2.4 amendments go into the RUN-STREAM and DELIV plan files.

## 14. Review round 1 map (Dennis, `68d581ba243c`)

| Finding | Where resolved |
|---|---|
| BLOCKER 1 live leak (`date_shift` and `fpe` on any detector) | Section 2.1; slice E-F0 first; AT-A1a, AT-A1c, AT-A1e; section 7 rows 1 and 2; section 12 OQ-2 |
| H2 A8 split, choke point, plan amendments, routes | Sections 2.2 (A8a, A8b), 2.4; AT-A8a, AT-A8b; section 10 C-F1a, C-F1b and ordering (rows 61 and 63a); OQ-7 |
| H3 FK dtype narrowing | Dropped; section 1 non-goals |
| H4 A5 instrument, callees, parity | Section 2.3; AT-A5, AT-A5b |
| M5 replacement fixtures | AT-A1f; AT-A1d span counts |
| M6 slice file overlaps | Section 10 ordering (serial surface lane) and E-S1b dependencies |
| M7 import-guard scope and split | Section 4 D2, D3 and the allowlist; section 7 import-guard row; C-S1a, C-S1b |
| M8 delegate rule | Section 7 re-export row |
| M9 inline-allowlist guard scope | Section 5 E2; section 7 allowlist row |
| M10 AT-A7 red on base | AT-A7 |
| M11 B7 contract text, `SecretCachePolicy`, AT-K1 scope | Section 3 B7; AT-B7; AT-K1 |
| LOW slice counts | Sections 0 and 10 |
| LOW E6 list | Section 5 E6 |
| LOW section 8b callers | Section 8b Lists |
| LOW comment-pattern negatives | Section 5 scanner patterns; AT-CH |
| LOW `ci.yml` fetch-depth comment | Section 5 E3 |
| LOW `dp.py` and `dp_session.py` docstrings | Section 4 D9 |
| LOW B8 registry tests at E-S1a | Section 3 B8 |
| LOW D6 coded refusal | Section 4 D6; AT-D6 |
| LOW emit-helper count location | Section 2.2 emit row (no count exists; none added) |

## 15. Review round 2 map (Dennis, `68d581ba243c`)

Verdict received: NO-GO, 0 blocker, 1 high, 9 medium, 7 low. H1 is `V1`; M9 is
`DESIGN` because the earlier plan would have created a second target-key validator. The remaining
items are `V2-LOG` plan and coverage corrections and do not independently decide the verdict.

| Finding | Label | Where resolved |
|---|---|---|
| H1 A8b writers | V1 | Sections 2.2 and 2.4; section 7 A8b choke point; AT-A8b; section 8b Lists; C-F1b |
| M1 AT-A1f inventory | V2-LOG | AT-A1f grep and complete anchored fixture list |
| M2 unreachable route cells and date spans | V2-LOG | Section 2.1 default-config statement; AT-A1d direct kernel cells; section 8b Routes |
| M3 `checks_passed` plan YAML drift | V2-LOG | Section 2.1 compile ownership and three list tails; AT-A1d support; section 8b Fields; section 8c contracts; E-F0 slice |
| M4 leak wording and draw-site digest | V2-LOG | Section 2.1 wording and pin paragraph; E-F0 slice |
| M5 runtime error value isolation | V2-LOG | Section 2.1 tagged `ConfigError`; AT-A1e; section 8b Exit paths |
| M6 RUN-STREAM r6-5 amendment | V2-LOG | Section 2.4 amendment notes, including lines 197, 226, 790-793 and 1160 |
| M7 A5 boundary inventory and parity | V2-LOG | Section 2.3 callee table and activation metric; section 7 A5; AT-A5b; Placement |
| M8 E-F0 release order | V2-LOG | Section 10 E-F0 release and repin rows and Ordering |
| M9 one unknown-target validator | DESIGN | Sections 2.2 and 6; section 7 A8a choke point; AT-A8a; Placement; E-F1 and C-F1a |
| L1 `text_mask.py` ceiling | V2-LOG | E-F0 slice line budget; section 9 keeps the existing module and forbids raising 670 |
| L2 both `_FPE_CONFIG` defaults | V2-LOG | Section 2.1 runtime paragraph |
| L3 section 7 mutation effect | V2-LOG | Section 7 detector-and-strategy mutation |
| L4 strict predicate inputs | V2-LOG | Section 2.1 predicate and compile-check paragraph |
| L5 detector set derivation | V2-LOG | Superseded by revision 4's two exact derived inventories in section 2.1 and their equality guard |
| L6 E-F0 estimate | V2-LOG | Section 10 E-F0 row, at most 10 production files and 800 total changed lines |
| L7 AT-A5 placement | V2-LOG | Section 7 A5 guard, AT-A5b and section 9 Placement |

## 16. Codex review after revision 3

Verdict received: NO-GO, one `V1` and one `V2-LOG`. No `DESIGN` finding was raised. The `V1`
decides the verdict; the `V2-LOG` scope correction does not.

| Finding | Label | Where resolved |
|---|---|---|
| E-F0 accepted detector selectors that `iter_spans` cannot execute because the plan derived one inventory from every `DETECTOR_DEFAULTS` key | V1 | Section 2.1 defines exact selector and override inventories from `_SPAN_DETECTORS`, `NER_ENTITY_MAP`, and the documented `DETECTOR_DEFAULTS` library-extra-span source; section 6 names one fact source per inventory; section 7 adds the equality guard and named mutation; AT-A1d distinguishes the inventories; fail-before AT-A1g refuses `iso_date` and `person_name`; sections 8b, 9 and 10 carry the route, placement and slice effects. The shipped-surface paragraph records that no template, init output, testflight manifest, proof manifest or docs example requires migration. |
| AT-A1f grep covered only three test subtrees | V2-LOG | AT-A1f widens the same inventory command to all of `tests/`. |
