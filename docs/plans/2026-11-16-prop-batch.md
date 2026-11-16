Status: plan

# PROP batch: quiet fallbacks, unused public names, shims and guard facts (roadmap rows 24zi, 24zj, 24zk, 24zl)

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `proportionality.md`, `cross-cutting-concerns.md`,
`api-and-compatibility.md`, `testing.md` (test depth); engine `CLAUDE.md`, `CODEMAP.md`
("Where Things Go"), `docs/frozen-surfaces.md`; CLI `docs/ROADMAP.md` (rows 24zd, 24ze, 24zi to
24zl, 63a, 93), CLI `CODEMAP.md`, CLI `docs/roadmap/post-1.0-plan.md`; owner memory rules: V1
bar, process by risk (2026-11-10), sentry over prose, pre-release no locking, no new features
(2026-11-16).

Revision 1, not yet reviewed.

Bases (2026-11-16): engine `origin/main` `13c95c7de` (includes 0.27.0, RUN-STREAM E5a #604 and
E5b #605); CLI `origin/main` `60cac678` (pins `decoy-engine==0.27.0`); platform `origin/main`
`fbaee2a9` (pins `decoy-engine==0.18.0`, parked; read only to record consumers). Input: the audit
`C:docs/records/2026-11-15-proportionality-audit/REMEDIATION.md` sections 4, 5, 7, 8, 14 and
15. The audit was read at engine `64e9349b` and CLI `e716f445`; every line number below was
re-read at the bases above and some differ from the audit.

Notation: `E:` is engine `src/decoy_engine/`, `ET:` is engine `tests/`, `C:` is CLI
`src/decoy/` (and `C:` plus a repo path such as `C:docs/` for CLI repo files), `CT:` is CLI
`tests/`.

## 0. Why this plan is in the engine repo

Of the 15 slices below, 9 land in the engine: all of package B, most of A and D, and the engine
half of E. The CLI slices are smaller, and three of them do not depend on an engine release. The
plan sits in the repo that holds most of the work so the gate has one place to look; each CLI
slice names its CLI paths in full.

## 1. Pinned guarantee and non-goals

Guarantee. After this batch:

- (a) no failure listed in 24zi turns into a weaker output while the run reports success;
- (b) every public engine name listed in 24zj has a recorded consumer or is gone;
- (c) no CLI line probes for an engine name that the exact pin already ships, and no engine
  module exists only to re-export another;
- (d) each guard fact listed in 24zl is written in one place, and a new comment that carries a
  task id, review round, date or reviewer name fails a guard.

Non-goals:

- No new feature. Each item is a fix to existing behavior or a deletion.
- D13 (`_V2_CUSTOM_PROVIDERS` beside `_CUSTOM_FAKER_PROVIDERS`) is not a shim: both tables are
  live. It goes to the post-1.0 plan as a duplication item.
- B9 (platform reason codes) stays as the platform wire contract. Reason codes are append-only.
- E5 (exact line pins on four legacy CLI files) stays until V1 (owner 2026-11-15). E8 is V1+.
- Audit packages C, F, G, H, I and J are not in these rows.
- No platform change. The platform is parked on engine 0.18.0. A name it uses is kept and the
  consumer is recorded.
- Compatibility window: `api-and-compatibility.md` asks for a documented window before a removal.
  The owner's pre-GA hard-delete rule (row 24zk text) is that window: no 1.0 has shipped, and the
  0.28.0 release notes list every removed name.

## 2. Row 24zi PROP-FALLBACK

No item is fixed on main.

| Item | Site (at base) | Defect | Reachable | V1 behavior | Slice |
|---|---|---|---|---|---|
| A1 | `E:transforms/text_mask.py` `_mask_faker`, `_mask_span` (468-510) | The audit named the inner `try` in `_mask_faker`. That catch is unreachable (`shared_faker()` is a default-locale `Faker()`). The reachable defect is next to it: `per_detector_strategy` values are never checked. `faker` on a detector with no `_FAKER_METHOD` entry (email, ssn, phone and others) writes a fake person name into that span. An unknown strategy name (a typo such as `fakr`) falls to the redact token in `_mask_span` ("redact and any unknown strategy ... fail-safe"). Both run and report success. | Yes, from any config. Read unchecked at `E:execution/_strategies/_text_mask.py:100`, `E:execution/out_of_core/_mask_group_c.py:259`, `E:execution/out_of_core/_text_mask_native.py:75`, `E:execution/native/_operator_params.py:243`. | Compile refuses with the existing code `config.mask.unknown_strategy` (`E:reasons/config/_part1.py:252`) for a value outside the strategy set, or `faker` on a detector with no Faker method. The `_mask_faker` inner `try` and its `fake.name()` fallback go. The unknown branch of `_mask_span` raises instead of redacting. | E-F1 |
| A2 | `E:transforms/geo_generalize.py` `_build_state_map` (272-288) | A failed `load_table("us_zip5_city_state")` returns `{}` with a warning, so every state value is `""`. | Only on a broken install (the table ships in the wheel). | The load error propagates. | E-F1 |
| A3 | `E:plan/_seed_envelope.py` (~127) | `except _ProviderError: reg_caps = None`. | No. `check_unknown_provider` runs first at `E:plan/_compile.py:190`, and in the config-only checks at 514. | Catch deleted. | E-F1 |
| A4 | `E:plan/checks/_generate_columns.py` `_expression_refs` | `except Exception: return frozenset()`: a bad expression becomes "no references". | No. `_check_parse_rules` runs before `_check_forward_references`, and `DerivedConfig.from_dict` already compiles the only `ref_kind="expression"` field. | Catch deleted. | E-F1 |
| A5 | `E:execution/_unified_slice.py` (~359) | `except Exception` logs `_REROUTE_LOG` and reruns the slice on pandas. A native bug becomes a slower correct run. | Yes, on any native-lane exception. Output does not change (the pandas oracle is correct). | Coded declines and the existing `ShadowDifference` path keep the reroute; any other exception propagates. Owner question OQ-3. | E-F2 |
| A6 | `E:execution/physical/_compiler.py` `_post_scan_resident` (~437-445) | `except Exception: return None` around `post_scan_resident_for(...)`, evidence only. The runtime calls the same function with no catch. | Only on an internal bug. | Catch deleted. | E-F1 |
| A7 | `C:cli/init.py` `_validate_scaffold` (~315-332) | `try: import yaml; from decoy_engine.config import parse_pipeline_config except Exception: return`. Both are hard dependencies, so a broken install skips scaffold validation. | Only on a broken install. | Plain import. | C-F1 |
| A8 | `C:cli/io/_targets.py` `write_targets` (~461-495); `C:cli/run/_execute.py` `_write_mask_outputs` (~291-310) and its copy in `C:cli/demo.py` (~295-303) | The audit named `getattr(result, "outputs", None)`, which is unreachable (`ExecutionResult.outputs: dict[str, pa.Table]`). The reachable defect is in `write_targets`: `table = outputs.get(table_name); if table is None: continue`. A declared file target with no output table is skipped and the run exits 0 with a missing file. Engine #584 (LOADER-DROP) closed one cause; the skip still hides any other. | Yes, on any engine result that lacks a declared table. | Before the first write, `write_targets` refuses when a declared target has no table: coded CLI error, exit 3 (OQ-7), no file written. The `getattr` checks become plain `result.outputs`. | C-F1 |
| A9 | `C:cli/run/_render.py` `_next_hint_for_run` (~53-61), used at ~168 | Reads `raw_cfg["output"]["path"]`, a key the V2 schema does not have, inside `try/except: pass`. Always None. | Dead code. | Deleted; the caller drops the keyword. | C-F1 |
| Emit helpers | `E:context.py` `emit_step`, `emit_lineage`, `emit_fidelity`, `emit_quarantine`, `emit_throughput_sample` | Five copies of `getattr` probing plus `except Exception: pass`; `emit_step` also retries without `node_id` on `TypeError` (D12). | The catch is a deliberate observation boundary ("a raising sink is counted, never propagated", `E:progress.py`). The five copies and the `TypeError` retry are the defect. | One private dispatch helper owns the probe and the catch. The `TypeError` retry goes. `emit_fidelity`, `emit_quarantine` and `node_id` go with B5. | E-S1b |
| FK dtype | `E:execution/_chunked_fk_dtype_safety.py` `arrow_type_is_fk_hash_safe`, `declared_fk_hash_dtype_is_safe` | Broad `except Exception: return False` around `zoneinfo.ZoneInfo` and the `pa.timestamp` and `pa.decimal*` constructors. Fails closed. | Yes, on a bad tz or width; the result is a refusal, which is correct. | Catch narrowed to the named errors (`ZoneInfoNotFoundError`, `ValueError`, `TypeError`, `pa.ArrowInvalid`). | E-F1 |

Failure modes:

- A1: a config that runs today with `faker` on an email detector now fails compile. This is the
  intended change; today it writes wrong values that look masked. The message names the detector
  id and the strategy, never a cell value. `decoy validate` refuses it too, because the check is
  wired into the config-only check list as well.
- A1: the strategy set must have one source. `_mask_span` and the new check both read one
  constant, `TEXT_MASK_STRATEGIES`, in `E:transforms/text_mask.py`. The four config readers keep
  reading the map; only compile validates it.
- A5: a native exception that rerouted today now fails the run. The test flight in OQ-3 counts
  such reroutes on the golden corpus before merge.
- A8: a chunked run writes through its own sink and never reaches `write_targets`. The choke point
  covers the non-chunked path, which is the path with the skip. The refusal comes before any
  write, so no partial file set is left.
- A2: a working install sees no change, so the test injects a loader failure.

## 3. Row 24zj PROP-SURFACE

The CLI uses none of these names (`git grep` at `60cac678`). Platform hits are listed where they
exist.

| Item | Names | Consumers found | Verdict | Slice |
|---|---|---|---|---|
| B1 | `_F9_KEPT_BINDINGS` in `E:__init__.py` (~342-365): `BundlePool`, `CompositeAddress`, `PoolCache`, `composite_city_state_zip`, the `Ein`/`Mrn`/`Ndc`/`Npi`/`Ssn` `Adapter`, `Domain` and `Validator` names, `IdentifierError`, `IdentifierFormatError` | `ET:unit/test_identifiers_subimport.py:46-47` only; platform hits are archive logs | Delete the top-level bindings. The names stay importable from their own modules (`decoy_engine.identifiers` and the pool modules). | E-S1a |
| B2 | `deterministic_hash` (`E:internal/crypto.py:18`) | none in src; `ET:unit/internal/test_crypto.py`, and a row in `ET:sentry/test_deprecation_expiry.py` if present | Delete with its tests and any expiry row. | E-S1a |
| B3 | `ExecutionContext.resolve_connector`, `captured_outputs`, `pool_resolver`, `column_relationships`, `_exports`, `_current_node_id`, `export()` | none; the platform builds only `ExecutionContext(logger=...)` (`api/storm/router.py:1297`) | Delete. `logger`, `derive_key`, `pipeline_derive_key` and `instance_default_locale` stay (read by `E:execution/_pipeline_full_frame.py`, `_pipeline_mixed_route.py`, `physical/_shadow_generation.py`). | E-S1b |
| B4 | `TelemetryClient`, `ExecutionContext.telemetry` | none | Delete. | E-S1a |
| B5 | `emit_fidelity`, `emit_quarantine`, `emit_step(node_id=)` | tests only; platform `api/persistence/logger.py` implements the sink methods, on engine 0.18 | Delete the two helpers and the keyword. The sink methods the platform implements are its own names, so nothing breaks there. | E-S1b |
| B6 | `ExecutionEvent` (`E:execution/_events.py`) | never built | Delete the module and both exports. | E-S1a |
| B7 | `run_pipeline` keywords `progress_interval_s`, `secret_registry`, `secret_cache_policy`, `stream_chunked_output` | no caller anywhere; `stream_chunked_output` has 12 src lines in 6 files and 3 test lines | Delete. | E-S1b |
| B7 | `chunked_dispatcher_enabled`, `multi_table_dispatch_enabled` | platform `api/jobs/v2_runner.py:263-264` | Keep; record the consumer in `docs/frozen-surfaces.md`. | E-S1b (doc line) |
| B7 | `use_byte_estimate_routing`, `use_probe_routing` | `E:capacity.py` passes `False`; `E:execution/__init__.py` documents them as the rollback path; also read by the physical `_snapshot` | Owner question OQ-4. Recommended: keep as documented rollback switches, consumer recorded. | E-S1b (doc line) |
| B8 | `FK_SELF_REFERENCE` alias at `E:validation_result.py:367`; `event_to_legacy_dict` (`E:_progress_events.py:598`, exported from `E:progress.py` and `__all__`) | tests only | Delete the alias (the code `fk.self_reference` stays). Delete `event_to_legacy_dict`; keep `_LEGACY_FIELDS`, which `event_to_dict` reads. | E-S1a |
| B9 | platform reason codes | platform wire contract | Stays. | none |

Each deletion updates, in the same slice: `docs/frozen-surfaces.md`, `ET:unit/test_public_api.py`
(`test_all_lists_every_public_name`), `ET:unit/execution/test_r3_public_signature_freeze.py`
(B7 only), and `CHANGELOG.md` under "Removed". `ET:sentry/release/test_frozen_surface_map.py`
then proves the page matches `__all__`.

Failure mode: an outside user importing a removed name gets `ImportError` or `AttributeError`.
That is the intent before 1.0.

## 4. Row 24zk PROP-SHIMS

No item is fixed on main.

| Item | Site | Change | Slice |
|---|---|---|---|
| D1 | `C:_native_gate.py` ~489-509 (`inspect.signature(run_pipeline)` probe for `unified_slice_enabled`; `import inspect` at 48) | Pass the keyword. It is in `run_pipeline` (`E:execution/_pipeline.py:152`) in the pinned 0.27.0. | C-S1 |
| D2 | `except ImportError` around `decoy_engine.keyprovider`, `ExecutionError` and `NerUnavailableError`: `C:_mask_secret.py:77`, `C:_mask_secret_guidance.py:51-76` and 140 (`_OLD_ENGINE_HEAD`, `_OLD_ENGINE_TAIL`, `OLD_ENGINE_RUN`, `OLD_ENGINE_TOKENIZE`, `OLD_ENGINE_API`), `C:api.py:151-152`, `C:cli/exit_codes.py:274,280`, `C:cli/run/_errors.py:138,150`, `C:cli/run/_prepare.py:428-429`, `C:cli/tokenize.py:306-307` | Plain imports; delete the `OLD_ENGINE_*` texts. Not touched: optional-dependency guards at `C:_private_file.py:45` (Windows `fcntl`), `C:ci/engine_logging.py:29`, `C:cli/compile_explain.py:345`, `C:cli/extras.py:195`. | C-S1 |
| D3 | `getattr(decoy_engine, "native_companion_status", None)` at `C:_native_gate.py:139` and `C:cli/preflight.py:552`; `hasattr(_engine_execution, "estimate_job_capacity")` at `C:cli/preflight.py:397`; `getattr(engine_errors, "EnvFlagError", None)` at `C:cli/exit_codes.py:233` | Plain attribute access. | C-S1 |
| D4 | `C:cli/report.py` ~893, `import pandas` guard | Delete (pandas is a hard dependency). | C-S1 |
| D5 | `C:cli/run/_execute.py` ~339-352, `_report_kwargs` left out "so the default call shape stays valid on an older engine" | Pass the keywords. | C-F1 (same hot file as A8) |
| D6 | `C:cli/io/_scan_set.py` `_LEGACY_FIELD_*`, `_from_legacy`, `_legacy_field`; `C:cli/io/_targets.py` ~193 `_legacy_format_for_path` | Owner question OQ-5. Recommended: delete. | C-S2 (if yes) |
| D7 | `E:execution/out_of_core/_source.py`, a re-export of `LazySource` from `E:profile/_readers` | Move 8 src importers (`out_of_core/__init__.py`, `_preflight.py`, `_relation.py`, `_rewrite_pass.py`, `_route_policy.py`, `_runner.py`, `_stage.py`, `_stream_driver.py`) and about 16 tests; delete the module. | E-S2a |
| D8 | Re-exports in `E:execution/_mem_estimate.py` (~84-93), `_planner_columns.py` (through `_planner`), `_sequential.py:169` (`table_topo_order`), `_chunked_fk.py` (~22-35), `_pipeline_routing.py` (~22-40), `native/_dispatch.py` (`noqa: F401 -- re-exported for tests`) | Importers move to the owning module; the re-export lines go. `run_pipeline` imports the owning modules directly. | E-S2b |
| D9 | `E:quality/dp_budget.py` ~499-520, a module `__getattr__` that re-exports `OpenDpReleaseSession`, plus an empty `if TYPE_CHECKING: pass` | Delete. It is an old import path of a public module, so it goes in the compatibility slice. | E-S1a |
| D10 | `E:execution/_fk_key_compat.py`, a one-line delegate to `_fk_keys.fk_key_value` | Importers (`_pandas_adapter.py:51`, `ET:unit/execution/test_pandas_adapter_helper_kills.py:14`) move; delete; drop its rows in `ET:sentry/layout/test_module_size.py` and the seam test. | E-S2a |
| D11 | `E:execution/_chunked_adapter_gate.py`: `chunked_adapter_touches_pandas_ingestion` always returns True | Fold the constant into the one caller (`_chunked_oracle.py:32`) and remove the dead branch; delete the module and its test references (`ET:unit/execution/test_de10_chunked_fk_passthrough.py:365`). | E-S2a |
| D12 | `E:context.py` `emit_step` `TypeError` retry | Goes with the emit dispatch helper. | E-S1b |
| D13 | V2 custom-provider table | Not a shim; out of scope (section 1). | none |

Failure modes: D1 to D5 rely on the exact engine pin. If the pin ever moves backwards, the plain
import fails at import time with an `ImportError` naming the module, which is the right failure.
D7, D8, D10 and D11 are private paths. A missed importer fails at import, so each E-S2 slice runs
`python -c "import decoy_engine; import decoy_engine.execution"` and the seam tests on the VM in
addition to T1.

## 5. Row 24zl PROP-GUARDS

| Item | Today | Change | Slice |
|---|---|---|---|
| E2 | Each allowlist is written up to four times: an in-code constant in the sentry, `tests/sentry/baselines/<id>.json`, a row in `scripts/dev/sentry_registry.toml`, and a `Source` in `tests/sentry/_baseline_sources.py` (engine 36 rows, 19 `in_code`; CLI 26 rows). | The baseline JSON is the only allowlist. One loader, `load_allowlist(sentry_id)` in `tests/sentry/_ratchet.py`, reads it; each sentry calls it and loses its in-code constant. `SOURCES` stops being a hand table: it is built from `sentry_registry.toml` (id, JSON path, kind). `test_baseline_registry.py` keeps its job (every registry row has a JSON, every JSON has a row). The shrink-only ratchet is unchanged. Row 24ze builds on this loader. | E-G2a, E-G2b, C-G1 |
| E1 | Hand list `SENTRIES` in `tests/sentry/test_sentry_manifest.py` (engine about 106 entries, including `tests/secret_providers/test_leak_sentry.py`; CLI about 72). The test cross-checks `scripts/dev/gates.sh` `SENTRY_PATHS`, `LAYER_TEST` and `LAYER_IGNORE`. | `SENTRIES` becomes the glob `tests/sentry/**/test_*.py` plus an explicit tuple of the paths outside `tests/sentry/`. The gates.sh cross-check stays. | E-G1, C-G1 |
| E3 | `ET:sentry/test_physical_seam_disconnection.py` (1057 lines) holds `test_production_execution_modules_are_byte_identical_to_origin_main` (~296) and its ~720-line allowlist. | Delete that test and its allowlist (owner 2026-11-15). Keep the import-direction tests (~164-221 and ~1039). Update the two CODEMAP rows that describe the seam guard. | E-G1 |
| E4 | `CT:sentry/layout/test_codemap_paths.py` pins the `KINDS` frozenset of verbatim row titles. | Drop `KINDS`; keep the path-exists test. | C-G1 |
| E6 | Baseline header pins (`doc["created_in"] ==`, `sentry_id`, registry text) in seven CLI files (the audit said six): `CT:sentry/cli_text/test_one_error_emitter.py`, `cli_text/test_stdout_writes.py`, `defects/test_exit_code_owner.py`, `io_policy/test_config_load_choke_point.py`, `io_policy/test_environment_reads.py`, `io_policy/test_private_files.py`, `test_outbound_clients.py`. The engine has none. | Delete the header asserts; `test_baseline_registry.py` already checks every baseline header once. | C-G1 |
| E7 | `ET:sentry/test_wave_b_no_registry_version_literal.py` (obsolete since REG-RELEASE: `REGISTRY_VERSION` moves only at release); `ET:sentry/test_perf_claim_provenance.py` (a forward invariant on `docs/`). | Owner question OQ-6. Recommended: delete the Wave B guard, keep the perf guard. | E-G1 |
| Comment history | No guard. | A sentry in each repo fails a new comment or docstring under `src/` that carries a task id, review round, ISO date or reviewer name. Baseline: per-file counts of today's hits in `tests/sentry/baselines/comment-history.json`, numeric `max`, shrink-only through the existing ratchet. | E-G3, C-G2 |
| K1 | `C:.github/workflows/regen-diagrams.yml` commits `docs/diagrams/{classes_decoy,deps,packages_decoy}.svg` as `github-actions[bot]` after each push to main, with `permissions: contents: write`. | Upload the three SVGs with `actions/upload-artifact`; `permissions: contents: read`; delete the committed SVGs; drop `docs/diagrams/*.svg` from `GENERATED_UNREAD_GLOBS` (`scripts/dev/gates.sh:65`) and the three entries in `CT:sentry/baselines/retired-name-pending.json` (~37-45). `CT:unit/scripts/test_gates_baseline_file.py:710-729` uses synthetic paths and stays. `C:docs/records/2026-11-08-cli-baseline-build.md` is a record and stays. | C-G2 |

Comment-history scanner:

- One pattern module, `tests/sentry/_comment_history.py`, written in the engine. The CLI vendors
  it byte for byte and pins it in `ci/vendored.toml`, as it already does for
  `tests/sentry/layout/_layout.py`. The patterns are written once.
- It reads `tokenize` `COMMENT` tokens and `ast` docstrings (module, class, function). It does
  not read other string literals, so reason texts and test data do not count.
- Patterns: ISO dates `\b20\d\d-\d\d-\d\d\b`; reviewer names (Dennis, Codex, Barry, argon,
  Fable); review phrases (`plan-gate`, `cold-read`, `round \d+`, `BLOCKER`); task ids
  (`(Task|Sprint|Slice|Wave|Row) [A-Z0-9][\w.-]*` and `\b[A-Z]{1,6}-\d+[a-z]?\b` minus an
  exclusion list of standards: `AES-\d+`, `SHA-\d+`, `UTF-\d+`, `RFC-?\d+`, `ISO-?\d+`,
  `CVE-\d+`, `GHSA-`, `PEP-?\d+`).
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

- New structure: one compile check module (A1), one private dispatch helper (emit), one loader
  (E2), one scanner module (comment history). Each replaces copies; none adds a variant expected
  to grow.
- One place per fact: the text-mask strategy set (`TEXT_MASK_STRATEGIES`), the allowlist (the
  baseline JSON), the comment patterns (the engine module, vendored by pin).
- Pattern followed: E2 copies the engine's `env_flags.FLAGS` pattern (one registry a sentry
  derives its inventory from). A1 follows `check_text_mask_ner_available` (row 30), a check in
  `plan/` wired into both check lists of `_compile.py`.

## 7. Choke points and guard mutations

| Class | Choke point | Guard test | Mutation that must turn the guard red |
|---|---|---|---|
| Text-mask strategy values (A1) | `E:plan/checks/_text_mask_strategy.py` `check_text_mask_strategies`, wired in `E:plan/_compile.py` beside `check_text_mask_ner_available` in the full and the config-only check lists | `ET:unit/plan/test_text_mask_strategy_check.py` | Remove the `_FAKER_METHOD` membership test: the `faker`-on-`email` case compiles. |
| Text-mask dispatch (A1) | `TEXT_MASK_STRATEGIES` in `E:transforms/text_mask.py`, read by `_mask_span` and by the check | same file, `test_dispatch_and_check_share_one_set` | Add a name to the dispatch only: the parity test fails. |
| Declared file target with no table (A8) | `C:cli/io/_targets.py` `write_targets`, a pre-write pass over declared targets | `CT:unit/cli_fmt/test_write_targets_missing_table.py` | Restore `if table is None: continue`: the test sees exit 0 and no refusal. |
| Native-lane reroute (A5) | the `except` in `E:execution/_unified_slice.py` | `ET:unit/execution/test_unified_slice_reroute_scope.py` | Widen the catch back to `Exception`: an injected `RuntimeError` reroutes. |
| Observation sinks (emit helpers) | one private `_dispatch_sink` in `E:context.py` | `ET:unit/test_context_emit_dispatch.py` | Delete the `except` in the helper: a raising sink fails the run. |
| Allowlist source (E2) | `load_allowlist` in `tests/sentry/_ratchet.py` (both repos) | new case `test_no_sentry_holds_an_inline_allowlist` in `tests/sentry/test_baseline_registry.py` (AST walk of `tests/sentry/**` for module-level `frozenset`, `set` or `tuple` constants that a registered sentry uses as its allowlist) | Re-add an inline `_ALLOWED = frozenset({...})` to one sentry: the case fails. |
| Comment history | `tests/sentry/_comment_history.py` | `tests/sentry/defects/test_comment_history.py` (both repos) | Drop the ISO-date pattern: the positive fixture `# fixed 2026-11-15` no longer fails and the self-test goes red. |
| CLI engine-import probes (D2, D3) | the exact pin in `pyproject.toml` | `CT:sentry/defects/test_engine_import_guards.py`, AST walk of `src/` for `try/except ImportError` and `getattr`/`hasattr` on a `decoy_engine` module; allowlist JSON of the four optional-dependency sites | Re-add `try: import decoy_engine.keyprovider except ImportError:` in one module: the walk fails. |
| Re-export-only engine modules (D7, D8, D10) | none needed beyond the walk | `ET:sentry/layout/test_no_reexport_modules.py`: AST walk of `src/`; a module whose body is only imports plus `__all__`, or an import line marked `noqa: F401` with "re-export", fails unless it is a package `__init__.py` or a facade in `PUBLIC_BOUNDARY_FILES` | Re-create `_fk_key_compat.py`: the walk fails. |

Each walk is shown to see a seeded violation in a scratch copy before its count is trusted.

## 8. Acceptance tests (fail before, pass after)

Each test is written first and must fail on the base commit named in the header, except where the
row says it pins a no-regression fact.

| Id | Test | Fails before because |
|---|---|---|
| AT-A1a | Compile a config with `text_mask` and `per_detector_strategy: {email: faker}`: `PlanCompileError` with code `config.mask.unknown_strategy`, the detector id in the message, no cell value. | Compiles; the run writes person names into email spans. |
| AT-A1b | Same with `{person_name: fakr}`. | Compiles; the span becomes the redact token. |
| AT-A1c | The config-only check list (the path `decoy validate` uses) refuses AT-A1a's config. | No check exists. |
| AT-A1d | `{person_name: faker}` and every pair in `_FAKER_METHOD` still compile and give byte-identical output to the base (golden). | Passes before; pins no regression. |
| AT-A1e | `_mask_span` with an unknown strategy raises (unit, bypassing compile). | Returns the token. |
| AT-A2 | Monkeypatch `load_table` to raise `FileNotFoundError`: `geo_generalize` with the state fallback raises it. | Returns `""` states with a warning. |
| AT-A3, A4, A6 | No behavior test (unreachable). An ordering test, `ET:unit/plan/test_compile_check_order.py`, pins that `check_unknown_provider` runs before `_build_seed_envelope` and `_check_parse_rules` before `_check_forward_references`. | Passes before; it pins why each catch is dead. |
| AT-A5 | Inject a `RuntimeError` into the native slice driver: `run_pipeline` raises it. A coded decline still reroutes and the output equals the pandas run. | Reroutes and returns success. |
| AT-FK | `arrow_type_is_fk_hash_safe` with an unknown tz returns False; with `ZoneInfo` monkeypatched to raise `MemoryError` it propagates. | `MemoryError` is swallowed. |
| AT-A7 | `_validate_scaffold` with `parse_pipeline_config` monkeypatched to raise `ImportError`: it propagates. | Returns silently. |
| AT-A8 | `write_targets` with two declared file targets and outputs for one: coded refusal, exit 3, neither file written. | Writes one file, exits 0. |
| AT-A9 | The run summary for a golden config is unchanged after the deletion. | Passes before; pins no regression. |
| AT-B | `ET:unit/test_public_api.py` lists the reduced `__all__`; `test_frozen_surface_map.py` passes with the edited page; `hasattr(decoy_engine, "BundlePool")` is False. | `__all__` holds the names. |
| AT-B7 | `test_r3_public_signature_freeze.py` pins the signature without the four keywords. | The signature has them. |
| AT-D | `test_no_reexport_modules.py` (section 7). | `_source.py`, `_fk_key_compat.py` and the D8 lines exist. |
| AT-C-D | `test_engine_import_guards.py` (section 7). | Eleven guarded sites. |
| AT-E1 | Add an empty `tests/sentry/test_zz_probe.py` in a scratch copy: the manifest test passes with no list edit. | The manifest fails until the list is edited. |
| AT-E2 | `test_no_sentry_holds_an_inline_allowlist` (section 7). | 19 engine sentries and the CLI `InCode` sentries hold inline constants. |
| AT-E3 | The seam test file runs no `git show origin/main:`; the import-direction tests still fail when a fixture module under `execution/` imports `execution.physical`. | It calls git and compares bytes. |
| AT-E4, E6 | Rename a CODEMAP row title in a scratch copy: `test_codemap_paths` passes. Change one baseline's `created_in`: only `test_baseline_registry` reacts. | `KINDS` and the seven header asserts fail. |
| AT-CH | Positive fixtures (one per pattern family) fail the scanner; negative fixtures (`AES-256`, `UTF-8`, `SHA-256`, `RFC 3339`, a date inside a string literal) pass; the real tree passes against the committed baseline; adding `# per Dennis round 2` to a src file fails. | No scanner exists. |
| AT-K1 | `CT:sentry/tooling/test_no_bot_commits.py`: no workflow runs `git commit` or `git push` or holds `contents: write`, and `docs/diagrams/*.svg` is not tracked. | `regen-diagrams.yml` commits. |

## 8a. Class table (recurring defect classes)

| # | Class | How this batch handles it | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | The A1 refusal and the A8 refusal name the detector id, strategy, table name and target path only. No cell value is formatted. | AT-A1a and AT-A8 assert a marker cell value is absent from `str(exc)`, `exc.args`, `__cause__` and `__context__`. | Format `span.matched_text` or a sample row into either message: the marker check fails. |
| 2 | Cleanup missing on an exit path | A8 refuses before the first write, so no staged file is left. A2, A5 and the FK catch narrowing add no resource. | AT-A8 asserts the target directory holds no new file after the refusal. | Move the check after the first `write`: one file remains and AT-A8 fails. |
| 3 | State machine and concurrency | N/A: no state or thread is added. The emit dispatch helper keeps the current counted-not-raised sink rule. | | |
| 4 | Route parity and silent fallback | This is the batch's main class. A1 is checked at compile, before any route is chosen, so the full-frame, out-of-core and native routes see the same refusal. A5 removes a silent route switch. | AT-A1a runs `--chunked` and default runs of the same config; both refuse at compile. AT-A5 checks a non-coded exception does not reroute. | Wire the A1 check into only one check list: AT-A1c fails. Widen the A5 catch: AT-A5 fails. |
| 5 | Referential integrity | N/A: no key, FK or join behavior changes. The FK dtype narrowing keeps every current refusal. | AT-FK pins that a bad tz still returns False. | |
| 6 | Untrusted producer | The config is the untrusted input for A1; the check validates it once at compile, the trust boundary. Inside, `_mask_span` raises on a value the check should have refused. | AT-A1b, AT-A1e. | Drop the raise in `_mask_span`: AT-A1e fails. |
| 7 | TOCTOU on a path | N/A: A8 checks the in-memory outputs dict, not the file system. No path check is added. | | |
| 8 | Weak tests and overclaimed evidence | Each acceptance test is labeled in section 8 as fail-before or as a no-regression pin (AT-A1d, AT-A3/A4/A6, AT-A9). No-regression pins are never counted as red evidence. Every new walk sentry is shown red on a seeded violation before its count is trusted. | The builder records the base-commit result of each fail-before test in the PR body. | Replace a walk with a hand list: the seeded-violation check fails. |
| 9 | Refactor drift | The D shim deletions and the emit helper collapse must not change behavior. D11 folds an always-true predicate, so the oracle branch it guarded runs as today. The emit helper keeps the probe-then-count rule. | The existing unit and parity tests for each moved importer stay green on T1; AT-D; `test_context_emit_dispatch.py` asserts each `emit_*` still calls the matching sink method once and counts a raising sink. | Make D11's folded constant False: the chunked oracle tests fail. Swap two method names in the dispatch table: the emit test fails. |
| 10 | Frozen contract drift | B1 to B8 and D9 remove public names on purpose, recorded in `docs/frozen-surfaces.md`, `test_public_api.py`, the r3 signature freeze and `CHANGELOG.md` in the same slice. Reason codes are append-only: `fk.self_reference` stays; A1 reuses `config.mask.unknown_strategy`; A8 adds one CLI code. | AT-B, AT-B7, `test_frozen_surface_map.py`, `test_reason_registry.py`. | Remove a name from `__all__` without editing the page: `test_frozen_surface_map.py` fails. Delete the `fk.self_reference` code with the alias: `test_reason_registry.py` fails. |

## 8b. Enumerations (from the code at the bases)

### Routes

- Text mask runs on the full-frame strategy (`E:execution/_strategies/_text_mask.py:100`), the
  out-of-core group C path (`E:execution/out_of_core/_mask_group_c.py:259`), the out-of-core
  native path (`E:execution/out_of_core/_text_mask_native.py:75`) and the native operator path
  (`E:execution/native/_operator_params.py:243`). A1 refuses at compile, before route choice, so
  all four see it.
- A5 is the unified-slice route only (`E:execution/_unified_slice.py:359`).
- A8 is the CLI non-chunked write path only; the chunked path writes through its own sink.

### Exit paths

- A1: `PlanCompileError`, CLI exit 1 (config error), at compile and in `decoy validate`.
- A2, A5, A6, A7, FK narrowing: the original exception propagates; CLI exit 3 (runtime).
- A8: `TargetTableMissingError`, exit 3 (OQ-7), before any write.
- Emit helpers: no exit change; a raising sink is counted, as today.

### FK shapes

- N/A to the fixes: no FK behavior changes. The FK dtype narrowing keeps the same True/False
  answer for every key type the chunked FK route reads today (AT-FK).

### Fields (every key this plan adds or reads)

- No config key is added. A1 validates the existing `per_detector_strategy` map values.
- No result or report field is added. A8 adds one CLI reason code, `io.target_table_missing`.

### Output surfaces

- Masked output bytes: unchanged for every config that compiles after A1 (AT-A1d).
- Files on disk: A8 can now refuse a run that wrote a partial set before; it writes none.
- Logs: A5 removes the `_REROUTE_LOG` line for non-coded exceptions; A2 removes one warning.
- Public API: the B and D9 removals.

### Lists

- `_mask_span` strategies: `fpe`, `faker`, `date_shift`, `passthrough`, and `redact` (today
  reached as the fall-through). These five are `TEXT_MASK_STRATEGIES`.
- `_FAKER_METHOD` keys: `person_name`, `first_name`, `last_name`, `address`, `location`. Any
  other detector id with `faker` is refused.
- Readers of `per_detector_strategy`: the four sites in the A1 row. None changes; compile checks
  once before any of them runs.
- `write_targets` callers: `C:cli/run/_execute.py` `_write_mask_outputs`, `C:cli/demo.py`,
  `C:api.py:633`, `C:cli/tokenize.py:371`. All get the A8 refusal through the one choke point.
- `emit_*` helpers: `emit_step`, `emit_lineage`, `emit_fidelity`, `emit_quarantine`,
  `emit_throughput_sample`. Three remain after B5.
- CLI `except ImportError` sites on engine names: the eleven listed under D2, plus the four
  optional-dependency sites that stay.
- Engine sentry baselines: 36 registry rows (19 `in_code`, 5 `json_keys`, the rest `from_file`);
  CLI: 26 rows.

## 8c. Reuse inventory and frozen contracts

- Reuse: `config.mask.unknown_strategy` (existing engine code); the `plan/_compile.py` check lists
  that already carry `check_text_mask_ner_available`; the ratchet and `test_baseline_registry.py`
  in both repos; the CLI vendoring pin `ci/vendored.toml`; `scripts/test_flight.py` for OQ-3.
- Frozen contracts touched: `decoy_engine.__all__` and `docs/frozen-surfaces.md` (B1, B2, B4,
  B5, B6, B8, D9 removals); the `run_pipeline` signature (B7); the engine reason registry (no
  change); the CLI reason registry (one added code); CLI exit codes (A8 moves a run that exits 0
  today to exit 3, OQ-7). The JSON result schemas, report tags (unless OQ-5 is yes, which drops
  two old reader tags) and the masking output of every valid config are unchanged.

## 8d. Pre-mortem

| Risk | Guard |
|---|---|
| A1 refuses a config pattern users rely on (for example `faker` on `phone`) | OQ-2 asks the owner first; release notes name the refusal; AT-A1d pins every allowed pair. |
| A5 turns a rare native exception into failed customer runs | OQ-3 test flight before merge; E-F2 can ship after the 0.28.0 train. |
| A removed public name has an unseen outside user | Pre-GA rule; the platform was checked; the 0.28.0 notes list every removal. |
| A deleted shim still has an importer in a test outside T1 selection | Each E-S2 slice runs the import smoke and the full suite (moved or deleted tests are an escalation trigger). |
| The E2 move loosens a sentry by loading the wrong JSON | `test_baseline_registry.py` checks each row's path; each migrated sentry keeps its seeded-violation self-test. |
| The comment guard blocks normal work on false positives | Negative fixtures; the baseline holds today's hits; fixes go in the pattern module. |
| A8 fires on the chunked path by mistake | The chunked path never calls `write_targets`; AT-A8 includes a chunked run that still exits 0. |
| C-F1 collides with the open RUN-STREAM CLI slices | C-F1 waits for them (section 10). |

## 9. Placement

Checked against the engine and CLI CODEMAP "Where Things Go".

| New or moved thing | Path | CODEMAP row | Beside |
|---|---|---|---|
| A1 compile check | `E:plan/checks/_text_mask_strategy.py` | plan checks | `plan/checks/_generate_columns.py` |
| A1 strategy set | `TEXT_MASK_STRATEGIES` in `E:transforms/text_mask.py` | transforms (owning module) | `_FAKER_METHOD` |
| A1 tests | `ET:unit/plan/test_text_mask_strategy_check.py` | unit tests for the owning surface | existing `plan` tests |
| A5 tests | `ET:unit/execution/test_unified_slice_reroute_scope.py` | unit tests for the owning surface | existing unified-slice tests |
| Emit dispatch helper | private function in `E:context.py` | Public API (private helper in a public module) | the `emit_*` functions |
| A8 error and reason | `TargetTableMissingError` in `C:cli/io/_targets.py`; reason `io.target_table_missing` in the CLI reason registry | "Source readers and target writers" (`src/decoy/cli/io/`) | `write_targets` |
| A8 tests | `CT:unit/cli_fmt/test_write_targets_missing_table.py` | `tests/unit/cli_fmt/` | other target tests |
| Allowlist loader | `load_allowlist` in `tests/sentry/_ratchet.py` (both repos) | Sentry test (`tests/sentry/_ratchet.py`) | the ratchet functions |
| Comment-history pattern module | engine `tests/sentry/_comment_history.py`; CLI vendored copy at the same path, pinned in `ci/vendored.toml` | Sentry test helper; CLI vendored pin | `_ratchet.py` |
| Comment-history sentry | `tests/sentry/defects/test_comment_history.py` (both repos); baseline `tests/sentry/baselines/comment-history.json`; one registry row each | recurring-defect class rules in `tests/sentry/defects/` | other `defects/` sentries |
| Engine-import-guard sentry | `CT:sentry/defects/test_engine_import_guards.py`; baseline `CT:sentry/baselines/engine-import-guards.json` | same | same |
| Re-export sentry | `ET:sentry/layout/test_no_reexport_modules.py` | layout fitness functions | `test_module_size.py` |
| Bot-commit sentry | `CT:sentry/tooling/test_no_bot_commits.py` | test tooling rules | other `tooling/` sentries |

Every new element has a present consumer in the same slice; no slice merges a helper for a later
slice.

## 10. Slices

Production files exclude tests, baselines, docs and CI YAML. Each slice stays at or under 10
production files and 800 changed lines; a slice that grows past either splits at the boundary its
row names.

| Slice | Repo | Items | Prod files (est.) | Lines (est.) | Risk | Depends on |
|---|---|---|---|---|---|---|
| E-G1 | engine | E3, E1, E7 | 0 | -800 / +80 | R1 | none; first, so later `execution/` slices stop editing the 720-line allowlist |
| E-G2a | engine | E2 loader, registry-derived `SOURCES`, first half of the `in_code` sentries | 0 | ~600 | R1 | E-G1 |
| E-G2b | engine | E2 remaining sentries, `test_no_sentry_holds_an_inline_allowlist` | 0 | ~500 | R1 | E-G2a |
| E-G3 | engine | comment-history guard, pattern module, baseline | 0 | ~400 | R1 | E-G2b |
| E-F1 | engine | A1, A2, A3, A4, A6, FK dtype narrowing | 9 (`transforms/text_mask.py`, new `plan/checks/_text_mask_strategy.py`, `plan/checks/__init__.py`, `plan/_compile.py`, `transforms/geo_generalize.py`, `plan/_seed_envelope.py`, `plan/checks/_generate_columns.py`, `execution/physical/_compiler.py`, `execution/_chunked_fk_dtype_safety.py`) | ~350 | R2 (output change in a masking transform; a new compile refusal) | E-G1 |
| E-F2 | engine | A5 | 1 | ~120 | R2 (a native-lane exception now fails the run) | E-G1; OQ-3 answered; test flight clean |
| E-S1a | engine | B1, B2, B4, B6, B8, D9 | 9 (`__init__.py`, `internal/crypto.py`, `context.py`, `execution/_events.py` deleted, `execution/__init__.py`, `validation_result.py`, `_progress_events.py`, `progress.py`, `quality/dp_budget.py`) | ~300 | R2 (public API) | none |
| E-S1b | engine | B3, B5, B7, D12, emit dispatch helper | up to 9 (`context.py`, `execution/_pipeline.py`, and the files that carry `stream_chunked_output`, `progress_interval_s`, `secret_registry`, `secret_cache_policy`) | ~400 | R2 (public API, `run_pipeline` signature) | E-S1a (both edit `context.py`); split by keyword if over 10 files |
| E-S2a | engine | D7, D10, D11, re-export sentry | 10 (8 `out_of_core` importers, `_pandas_adapter.py`, `_chunked_oracle.py`; 3 modules deleted) | ~250 | R1 (private paths) | E-G1 |
| E-S2b | engine | D8 | up to 10 (`_mem_estimate.py`, `_planner.py`, `_sequential.py`, `_chunked_fk.py`, `_pipeline_routing.py`, `native/_dispatch.py`, the importers that move) | ~300 | R1 | E-S2a |
| Release | engine | 0.28.0; notes list every removed name and the A1 refusal | | | | E-F1, E-S1a, E-S1b; E-F2 if merged by then, else the next train |
| Repin | CLI | pin `decoy-engine==0.28.0` (engine repin checklist) | | | R1 | Release |
| C-G1 | CLI | E2, E1, E4, E6 | 0 | ~600 | R1 | none (the CLI keeps its own copy of the machinery); split E2 from E1/E4/E6 if over 800 |
| C-G2 | CLI | comment-history guard (vendored module), K1, bot-commit sentry | 0 (workflow YAML, SVG deletions) | ~300 | R1 | C-G1; E-G3 merged (vendored source) |
| C-S1 | CLI | D1, D2, D3, D4, engine-import-guard sentry | 10 (`_native_gate.py`, `_mask_secret.py`, `_mask_secret_guidance.py`, `api.py`, `cli/exit_codes.py`, `cli/run/_errors.py`, `cli/run/_prepare.py`, `cli/tokenize.py`, `cli/preflight.py`, `cli/report.py`) | ~350 | R1 | none (0.27.0 ships every name) |
| C-S2 | CLI | D6 (if OQ-5 yes) | 2 (`cli/io/_scan_set.py`, `cli/io/_targets.py`) | ~150 | R1 | none; fold into C-S1 if C-S1 stays under the caps |
| C-F1 | CLI | A7, A8, A9, D5 | 6 (`cli/init.py`, `cli/io/_targets.py`, `cli/run/_execute.py`, `cli/demo.py`, `cli/run/_render.py`, CLI reason registry module) | ~250 | R2 (exit code change on a run that exits 0 today) | the open RUN-STREAM CLI slices of row 63a (C1l, C1a, C1b) that edit `cli/run/_execute.py` merge first; no engine dependency |

Ordering: E-G1 first. After it, the E-F, E-S and E-G2/E-G3 lanes run in parallel in separate
worktrees. They touch different files except `context.py`, which E-S1a and then E-S1b own in that
order. The CLI lanes do not wait for the engine, except C-G2 (vendored module) and the repin.
Row 24zj merges before row 93 (REL-GATE). Row 24ze plans on top of E-G2b and C-G1.

Expected size: about 16 PRs. Production code is net negative; the B, D and E deletions remove
about 2,500 lines, most of them the E3 allowlist and the shims. New public names: none. New
private names: `TEXT_MASK_STRATEGIES`, `check_text_mask_strategies`, `_dispatch_sink`,
`load_allowlist`, `TargetTableMissingError`. New reason code: CLI `io.target_table_missing`. The
engine reuses `config.mask.unknown_strategy`.

Testing per slice (owner test-depth rule): T0 per edit, T1 impact selection per commit, gates run
T1 on the exact head. Full suite only on an escalation trigger: E-S1a and E-S1b (frozen contract),
E-G1, E-G2a, E-G2b and C-G1 (shared test machinery and moved or deleted tests), E-F1 (golden
output). All runs on the Mac or a VM through `~/bin/vm-run`, never on the devbox. Mutation testing
only on the E-F1 check and the C-F1 choke point (core logic).

## 11. Established solutions

- The R2 slices (E-F1, E-F2, E-S1a, E-S1b, C-F1) add no parser, scheduler, protocol or method.
  They delete catches, add one validation at an existing compile check list, and delete names.
  The patterns followed are in the codebase: `check_text_mask_ner_available` for the compile
  check, the frozen-surface update steps in `docs/frozen-surfaces.md` for removals.
- E2 follows the engine's `env_flags.FLAGS` registry pattern; no library needed.
- Comment scanning uses the standard library `tokenize` and `ast`. Ruff (the linter both repos
  run) has no rule that matches comment text against a project pattern list, so a small scanner
  is needed.
- K1: `actions/upload-artifact` is the standard way to publish CI build output.

## 12. Owner questions (each with a recommended answer)

- OQ-1. Scope split. The CLI post-1.0 plan (#284, its owner question 2) lists A2, A5, A6, A7 and
  A9 as "1.x patch" and A1, A3, A4 and A8 as "before 1.0 freeze". Row 24zi (owner 2026-11-15)
  puts all nine in V1. Recommended: do all nine in this batch. Each is small, and fixing them
  before 1.0 removes the 1.x contract question. If the owner wants the narrower set, E-F1 drops
  A2 and A6 and C-F1 drops A7 and A9, with no other change.
- OQ-2 (A1). Refuse at compile a `faker` strategy on a detector with no Faker method, and an
  unknown strategy name, with `config.mask.unknown_strategy`? Recommended: yes. Today's output is
  wrong values that look masked. Mapping each detector to a matching Faker method instead would
  be a new feature.
- OQ-3 (A5). Let an unexpected native-lane exception fail the run instead of rerunning on pandas?
  Recommended: yes, after a test flight (`scripts/test_flight.py` on the golden corpus and the
  prodsim set) on the E-F2 head shows no reroute from a non-coded exception. Any reroute it finds
  becomes a coded decline or a fix first.
- OQ-4 (B7). `use_byte_estimate_routing` and `use_probe_routing`: keep as documented rollback
  switches with the consumer recorded (recommended), or delete in E-S1b?
- OQ-5 (D6). Delete the readers for pre-`scan-set/v1` saved scans and pre-CLI-FMT manifests?
  Recommended: yes; pre-GA, and no 1.0 user holds these files.
- OQ-6 (E7). Delete `test_wave_b_no_registry_version_literal.py` and keep
  `test_perf_claim_provenance.py`? Recommended: yes to both.
- OQ-7 (A8). Exit code for a declared target with no output table. Recommended: exit 3
  (runtime). The config was valid and the engine did not produce the table.

## 13. Follow-ups outside this batch

- The memory note on the physical-seam sentry allowlist is out of date once E-G1 merges; the
  orchestrator updates it.
- D13 goes to the post-1.0 plan as a duplication item.
- The post-1.0 plan rows for B1 to B8, D6, D9 and A1 to A9 are marked done as each slice merges.
