# PROP-SURFACE wide: cut the engine root to its consumed names

Status: plan (revision 3, after Dennis round 2)

Row: 24zj PROP-SURFACE (1.0, `docs/roadmap/groups/health.md` in the CLI repo), widened by the owner on 2026-11-25.
Risk tier: R2 (public API, frozen contract). Gate: Dennis then Codex on this plan; Codex on each slice.
Inputs read from origin/main: engine `2b8a47fbe` (0.28.4), CLI `b9e5f5cd` (pins engine 0.28.3), platform
`be3c82377` (pins engine 0.18.0, parked). Also the PROP batch plan rev 7
(`origin/docs/plans-prop-reanchor-1125:docs/plans/2026-11-16-prop-batch.md`), TNR-09 and PROP-HANDOFF-2026-11-17.
Rules consulted: universal rules, risk and exceptions, development loop, scope discipline, API and compatibility, architecture, cross-cutting concerns, verification, code review, documentation and the recurring-defect catalog.

The inventory covers 230 original exports and 28 proposed additions. `at_root_before` identifies the original set. Each new row gives its defining module. Blank reader counts on additions mean the deletion test does not apply. The exclusions CSV covers the remaining 157 of the original 185 reached types. Its rows describe the input tree. W0 seeds its registry from the rows still reached after E-S1b.

## 1. Pinned guarantee and non-goals

Guarantee: when the last slice merges, every name in `decoy_engine.__all__` has a recorded reason to be there:
- a CLI or platform source consumer, including a callback implementation;
- a type reached from such a name (section 3, the type closure);
- a contract section that names it (`contract:§3.1`);
- a pairing with a kept name that it must not be split from (`pairs-with:`).

Every other root name is gone from `__all__` and from the module namespace. Tests fail if a name is added to the
root without a reason, if a public attribute exists on the root without being in `__all__`, or if a kept name
reaches an engine type that is neither at the root nor on the exclusion list with a reason.

This runs before the GA flip (`RELEASE_PHASE` in `src/decoy_engine/release.py:45`). After GA, removing a root export requires 2.0. Pre-GA removals leave no
shims, no `DeprecationWarning`, no `__getattr__` fallback, no kept bindings.

Non-goals:
- No 1.x TNR-API-MANIFEST (one manifest for every public path). The guard covers the root only.
- No change to `decoy_engine.sdk.__all__`. The thirteen unconsumed SDK re-exports leave the root.
- No platform edit. The platform is parked on 0.18.0; this plan records its consumers for the repin (section 10).
- No behavior change in any kept function. A moved object keeps its home module, code and tests.
- No growth of any ratchet baseline, allowlist, `SIGNATURE_EXEMPTIONS`, `TIER_EXCEPTIONS`,
  `EXPERIMENTAL_OBJECTS` or the new `CLOSURE_EXCLUSIONS`. They may only shrink. Census floors move only as section
  4, D1 says.

## 2. Inventory result

Method:
- Scan CLI production source under `src/` and platform production source under `api/`. Resolve each import to the defining engine object, including local imports, aliases, chained re-exports, private home paths and module attributes. Include literal string targets, `getattr`, `hasattr` and attributes of an assigned `importlib.import_module(...)` result. Record repository, path, line, object and access form. Test, spike and documentation hits stay separate.
- In platform `api/jobs/fixed_width_output.py:238-242`, the lookup reaches the root writer and the home-path exceptions `FixedWidthWriteError` and `DecoyError`. Preserve per-call lookup timing when changing the target at repin.
- Scan callback protocols implemented by CLI or platform classes. Enumerate every engine `Protocol`, including declarations under `TYPE_CHECKING`. Compare inherited methods, properties and signatures. Follow the object into the engine callback slot to confirm a match. A matching method name alone gives no evidence of use. The pass covered 54 protocols. Platform `JobLogger` supplies both `Logger` and `StructuredEvents` through `ExecutionContext(logger=...)` in `api/storm/router.py:1297`. CLI `ProgressFanout` supplies `ProgressSink` in `src/decoy/cli/run/_progress.py`. CLI `LocalTokenVault` also supplies `TokenVaultWriter`, and the platform file broker implements `FileAccess`. A structural match needs no new consumer import.
- Join all 185 prior exclusion rows to those results by qualified identity. A named or callback consumer takes priority over every exclusion category and every closure-only reason. For example, the two engine `ColumnProfile` classes have different definitions. Only the profiling class has the platform import.
- Engine readers: a word-boundary search (`grep -rnw`) of every name over all of `src/` and all of `tests/`,
  `scripts/`, `testflight/` and `examples/`. Re-export lines in package `__init__.py` files and the definition line
  are not readers.
- The type closure: section 3, rule 3, run at runtime with `typing.get_type_hints`.

A type yielded or returned by a src function counts as a src reader, including inside a container or a shared iterator. Trace its callers.

Delete rule (HIGH-3): an object is deleted only when it has no reader in `src/` and no reader in tests. Three test
kinds do not count, because they exist only to test the object and go with it: the object's own unit test file,
its row in a public-API presence list (`tests/unit/test_public_api.py`), and its row in a registry exemption list.
Any other test counts as a reader: security, determinism, golden, integration, f29 baselines, sentries. A name
with such a reader is a move.

| Verdict | Count | Meaning |
|---|---|---|
| keep | 128 | CLI or platform source imports it, reads it dynamically or implements its protocol |
| keep-closure | 48 | Reached by the type closure from a kept name (section 3, rule 3) |
| keep-contract | 4 | `RunResult`, `RunResultRead`, `RUN_RESULT_SCHEMA`, `ScanSetCore`: contract §3.1 names them as the artifact models |
| keep-pairing | 1 | `profile_document`: the one redacting profile writer, paired with `profile_columns` |
| move | 70 | No consumer and no reason. Only the root binding and the `__all__` entry go; the object and its home path stay |
| delete | 7 | No reader under the delete rule. Root binding and object go. 5 are in E-S1a or E-S1b and 2 are in W7 |

Root after all slices: 181 names (230 original, plus 28 additions, minus 70 moves and 7 deletes). E-S1a also removes the 21 `_F9_KEPT_BINDINGS`, which are not in
`__all__`.

Deletes:
- In the batch plan, unchanged: `TelemetryClient` (B4), `ExecutionEvent` (B6), `event_to_legacy_dict` (B8),
  `emit_fidelity` and `emit_quarantine` (B5).
- W7 deletes only `register_secret_provider` and `ConnectorAuthError`. W5 moves `KeyedColumn` and `keyed_columns_for_config` to their existing public home, `decoy_engine.secret_providers`. The shared walk yields `KeyedColumn` at `secret_providers/_requirements.py:264`. Both the tuple-returning helper at line 271 and the CLI-used secret classifier at line 276 consume that walk. Preserve the pinned oracle and parity cases in `tests/secret_providers/test_keyed_columns.py`.

Former deletes that are now moves (they have readers): `CallbackSink`, `StructuredEventsSink` (security,
determinism and golden tests, f29 baselines), `IdentityDomain` (`tests/native/test_determinism_protocol.py`,
`test_draw_site_providers_golden.py`), `is_value_sensitive` (`profiling/_value_redaction.py:468`),
`reasons_from_report` (`tests/integration/test_f29_outcomes.py`).

Platform source consumers (engine 0.18 API, read at its pin):
- Through the root: `SEED_PROTOCOL_VERSION`, `DiscoverySqlError`, `SecretKeyProvider`, `apply_table_transforms`,
  `atomic_swap_db_providers`, `classify_table_kinds`, `estimate_job`, `list_generate_faker_providers`,
  `make_key_resolver`, `native_companion_status`, `read_fixed_width`, `run_discovery_sql`, `run_mask_chunked`,
  `run_pipeline`, `unmask_pipeline`, `write_fixed_width` (dynamic), plus `hasattr(decoy_engine,
  "apply_table_transforms")` in `api/engine_compat.py:287`.
- Through home or private paths: `ColumnProfile` (`profiling.types`), `CompositeError` (`composite._errors`),
  `ExecutionContext`, `FixedWidthParseError`, `MaskSecretError`, `PermanentError` and `TransientError` (`sdk`),
  `ProviderSpec` (`providers_v2._adapter`), `RelationshipGraph`, `StrategyError` (`execution._errors`),
  `ValidationMessage`, `ValidationResult`, `build_namespace_registry`, `build_relationship_graph`,
  `check_orphan_fk_policy_completeness`, `composite_*` (five), `job_seed_for_config`, `load_vault`,
  `run_mask_pipeline_chunked`, `composite_city_state_zip` (an F9 kept binding, imported from
  `generation.composite`, so B1 does not break it).
- `chunked_dispatcher_enabled` and `multi_table_dispatch_enabled` (`api/jobs/v2_runner.py:263-264`) are
  `run_pipeline` keywords, not root names; E-S1b keeps them.

The inventory gives the consumer paths for all W0 additions. C1 retargets names available on the current CLI pin. C2 retargets the seven newly exported types imported by CLI source on the first pin with W0 exports. CLI tests keep the root imports for `PhaseEvent`, `TerminalEvent`, `ProgressSink`, `QualityWarning`, `NativeCompanionStatus` and `profile_document`. C2 moves the test import of `event_to_dict`.

## 3. Behavior

After the stack:
1. `decoy_engine.__all__` holds exactly the keys of `ROOT_SURFACE` in the W0 release sentry (Placement), a mapping
   from each name to its reason string: `cli:<module>`, `platform:<module>`, `type-of:<kept name>`,
   `contract:§3.x <what>` or `pairs-with:<kept name>`.
2. `{n for n in dir(decoy_engine) if not n.startswith("_") and not ismodule(getattr(decoy_engine, n))}` equals
   `set(decoy_engine.__all__)`. No hidden bindings.
3. The type closure. Start from every name with a `cli:`, `platform:`, `contract:` or `pairs-with:` reason. For each
   object, collect:
   - `typing.get_type_hints` of a function (parameters and return), of a class (fields over the MRO), of its constructor, and of every
     public method and property of a class. The global namespace for each call is the module namespace plus the
     names the module imports under `if TYPE_CHECKING:`, so string annotations resolve;
   - every member of a `Union`, `Optional`, `Literal`-free alias, `Annotated` base, and container argument
     (`list`, `tuple`, `dict`, `Mapping`, `Sequence`, `Iterator`, `Callable` arguments and return). For example
     `ProgressSink.on_event` takes the `ProgressEvent` union (`_progress_events.py:419`), which expands to
     `PhaseEvent`, `RateSample`, `RouteEvent`, `WarningEvent`, `TerminalEvent`, `RetryEvent`, `CheckpointEvent`;
   - every engine exception named in a `Raises:` section or an explicit “raises X” sentence of the object or a public method (including `VaultWriter.close`), and the
     hints of that exception's attributes. For example `PipelineConfigError.problems` holds `ConfigProblem`, which
     the CLI reads at `src/decoy/cli/gate/_layers.py:150-178`;
   - engine base classes of a reached class.
   Repeat to a fixed point. Only objects whose `__module__` starts with `decoy_engine` count.
   Every reached engine type is either in `ROOT_SURFACE` or in `CLOSURE_EXCLUSIONS` (a mapping from qualified name
   to reason). A closure-only root name has the reason `type-of:<the name it was reached from>`.
   Any `get_type_hints` failure fails the test. The one failure today (`BundlePool.__init__`, `np` not resolvable)
   is fixed in W0 by resolving inherited dataclass field hints in the declaring class namespace. `ValuePool.values` uses both `np` and `Any`. Verify the generated constructor resolves both names.
4. `from decoy_engine import <moved or deleted name>` raises `ImportError`; every one is in `REMOVED_PUBLIC_NAMES`.
5. `from decoy_engine.<home> import <moved name>` still works and behaves as before.
6. A moved object that had no other frozen path is INTERNAL in the census. An object that keeps a frozen path
   (`sdk.ConnectorError`, `detection.ModelRef`, `profiling.ModelHit`) stays FROZEN.
7. `docs/frozen-surfaces.md` has one row entry per name left in `__all__` and per `sdk.` name.
8. `CHANGELOG.md` has a "Removed" entry per slice, and `changelog.d` has `Breaking:` lines naming every removed
   root object in backticks, so `test_public_signatures.py` passes.
9. The census walk and an independent static count agree (section 4, D1), and both are above fixed floors.

## 4. Doubtful cases and owner decisions

D1. Census floors (HIGH-5, option ii). `HEAD_FLOOR = 350` (`tests/sentry/release/test_public_signatures.py:32`)
and `MIN_NAMES = 1186` (`tests/sentry/release/test_public_census.py:25`) guard against a census walk that silently
sees fewer names. The plan keeps fixed nonzero floors and adds an independent count:
- W0 adds `test_static_all_matches_census_walk`. Discover the static package set from the file system alone. Start at `src/decoy_engine`, find package directories with `__init__.py`, skip paths with an underscore-prefixed component or an `internal` component, and subtract `NO_ALL_PACKAGES`. Include the root and the public module files `sdk.py` and `providers.py` explicitly. Read literal `__all__` from those sources. Reuse the AST literal rules in `tests/sentry/release/_census.py` for assignments, annotations and `+=`. Missing or unsupported declarations fail. Compare both the package sets and the exact export pairs with the census result, including statically handled optional packages. The census supplies only the observed side of that comparison.
- The two floors stay constants. Apply each floor to the population counted by its own sentry. A slice may lower a floor only in the same diff that removes the names, and only
  by at most the number of `(module, name)` pairs that diff removes. The PR body lists the names. Gate check F10
  rejects a floor edit in any other diff.
- At W7, target the measured value minus five. Retain the stronger floor if that target would exceed the permitted drop. Record the measured populations, removed names and final constants in the PR body and changelog.

D2. The inventory has 48 closure-only root names. W0 exports 27 reached types with external source evidence (26 named imports and one dynamic home lookup). The owner also requested the engine `PublicationState`. Its verified reason is `type-of:ReasonContext` (`reasons/_record.py:122`). The platform's `api/models.py:38` imports the scheduler enum defined in `api/scheduler/state_machine.py:81`. It has different members and database values. Keep that ORM binding in place.

The 157 remaining input exclusions have a category and a named edge in the CSV. The category describes the type's role in the defining module. It does not set its stability tier. For example, `config-model` covers configuration model components, `contract-run-result` and `contract-scan` cover the §3.1 artifact families, and `compiled-plan` covers unconsumed components of the compiled plan. `vault-secret` records types still reached through `VaultWriter`. Only `Clock`, `ResolveContext` and `ResolvedSecret` have the `removed-keyword` category. The input CSV has 80 config or §3.1 contract rows and 77 other rows. If B7 removes only those three paths, W0 seeds 154 rows and lists 74 individually in its PR body. Recompute reachability after B7. Carry only live rows into W0 and show every removed edge in its PR.

D3. `SecretCachePolicy`, `SecretProviderRegistry`, `SecretProvider`, `SecretDescriptor`, `SecretRef`. In the
`run_pipeline` closure only through the `secret_cache_policy` and `secret_registry` keywords that B7 (E-S1b)
deletes. After E-S1b they have no consumer, so W5 moves them. W5 stacks on E-S1b. `TelemetryClient` leaves the
closure through B4 (E-S1a).

D4. `RELEASE_PHASE`, `ReleasePhase`, `is_pre_ga` (LOW-1, accepted). No platform or CLI read. They move; the code
stays in `decoy_engine.release`, and every engine reader already imports from there
(`tests/integration/compat_corpus/test_compat_corpus.py:24`). Doc edits are in section 8.

D5. `ConnectorAuthError`. Defined in `errors.py:131`, never raised, listed in the root docstring. W7 deletes it with
its presence test and its exemption row in `tests/sentry/test_reason_registry.py:560`. The exception hierarchy
baseline loses one row (a shrink).

D6. SDK re-exports at the root (13 names: six `CAP_*`, `SDK_VERSION`, `CheckResult`, `ConnectorConfig`,
`FileMeta`, `FileSink`, `FileSource`, `WriteResult`). Experimental, no consumer. They move; they stay in
`decoy_engine.sdk.__all__`. `PermanentError`, `TransientError` and `ConnectorError` stay at the root.

D7. Exception subclasses with no consumer and no closure path (`ConfigRuleError`, `ValidationError`,
`PlanCheckError`, `WeakMaskSecret`, `DeterminismError`, `AdapterError`, `SecretProviderError`). Callers catch the
kept base. They move. The subclasses the closure reaches (`KeyedStrategyRequiresSecret`, `PoolCapacityError`,
`ProviderError`) stay.

D8. Retarget each real home-path consumer in its own repo. Use C1 for existing root exports, C2 at repin for W0 exports, and section 10 for platform. Test import identity as well as import success.

D9. `profile_document` and `redact_profile_dict` (HIGH-4). `profile_document` stays at the root as
`pairs-with:profile_columns`: it is the only writer that redacts a profile before it reaches a file. The CLI sentry
G-ONE-PROFILE-WRITER (`tests/sentry/io_policy/test_profile_document_route.py`) requires every CLI profile write to
go through it, `tests/unit/test_api.py:406` imports it from the root, and the `scan_file` docstring in CLI
`src/decoy/api.py:689` points callers at the engine profile path. Moving the writer while `profile_columns` stays
would make the unsafe route the easy one. `redact_profile_dict` moves to `decoy_engine.profiling`: it is the
redactor inside `profile_document`, its readers are engine tests that already import from `decoy_engine.profiling`,
and a second public serializer at the root would invite a write route the sentry does not see.

D10. The §3.1 names (MEDIUM-2, orchestrator decision). `RunResult`, `RunResultRead`, `RUN_RESULT_SCHEMA` and
`ScanSetCore` stay with `contract:§3.1` reasons. `ScanSetCoreRead` is not at the root today and is not added
(no growth); §3.1 already names its home path. The §3.1 text edit is in section 8.

## 5. Failure modes

| # | Failure | Guard |
|---|---|---|
| F1 | A consumer reads a root name the scan missed (dynamic `getattr`, string target, docs example). | Builder re-runs the scan script on the slice head. Non-literal root `getattr` sites to check by hand: `tests/unit/profile/test_csv_reader.py:319`, `test_vault_boundary.py:98`, `test_derived_route_matrix.py:116`, `test_ga_stub_exports.py:26`, `test_validation_sites.py:110`, `test_config_error_text.py:202`, `test_scan_diff.py:474`, `scripts/bench_multi_table.py:184`, `bench_auto_chunk.py:185`, `bench_unconfigured_passthrough.py:179`. |
| F2 | The CLI breaks at its next engine repin, in src or tests. | Slice C2 retargets CLI source and tests; the gate runs the full CLI suite against the engine stack top (section 9). |
| F3 | A name leaves `__all__` but its import stays in `__init__.py`. | W0 attribute-equals-`__all__` test (behavior 2). |
| F4 | A slice forgets `docs/frozen-surfaces.md`. | `test_frozen_surface_map.py::test_every_public_name_has_a_row` fails. |
| F5 | A slice forgets the `Breaking:` line. | `test_public_signatures.py` fails (OBJECT_REMOVED unannounced). |
| F6 | An `EXPERIMENTAL_OBJECTS` or `TIER_EXCEPTIONS` row goes stale. | `test_exceptions_are_unique_and_not_stale`, `test_experimental_objects_outside_sdk_are_real_exports`. A row goes only when no walked public path still exports the object. |
| F7 | Census tier drift: an object exported by two paths gets two tiers. | `test_one_object_has_one_tier_on_every_path`. |
| F8 | Sphinx `-W` fails on an autodoc reference to `decoy_engine.X`. | Each slice runs the docs build (CI gate mirror). |
| F9 | Root file budget (`<= 600` lines, `test_public_api.py:360`) drifts. | Check the existing 600-line cap on every head, including W0. Group public imports and shorten the existing root docstring if needed. |
| F10 | A builder "fixes" a failing guard by adding a name back, growing an allowlist or lowering a floor. | Gate check: W0 documents each new root key from the inventory. After W0 its keys only shrink during this stack. The existing lists `TIER_EXCEPTIONS`, `EXPERIMENTAL_OBJECTS`, `SIGNATURE_EXEMPTIONS`, `CLOSURE_EXCLUSIONS` may only lose lines; a floor constant may drop only in a diff that removes at least as many `(module, name)` pairs. |
| F11 | Docs and testflight scripts cite root names. | Each slice greps `docs/` (not `docs/records/` or dated `docs/plans/`), `examples/`, `testflight/`, `scripts/`. |
| F12 | A kept name gains a new engine type in a signature after the stack. | AT-W0e fails until the type is added to the root with a reason or to `CLOSURE_EXCLUSIONS` with a reason (an exclusion add needs owner sign-off, since the list only shrinks). |
| F13 | An exclusion row goes stale (type no longer reached). | `test_closure_exclusions_are_reached` fails; the row is deleted. |
| F14 | A delete removes an object a test still reads. | The builder re-runs the delete-rule search (section 2) on the W7 head; a hit turns the name into a move in that slice. |

## 6. Acceptance tests (fail before, pass after)

- AT-W0a: adding `"Foo"` to `__all__` and a root import, with no `ROOT_SURFACE` entry, fails
  `test_root_surface_has_a_reason_per_name`.
- AT-W0b: a public root binding not in `__all__` (the F9 pattern) fails `test_root_attributes_equal_all`.
- AT-W0c: a `type-of:run_pipeline` reason on a name the closure does not reach from `run_pipeline` fails
  `test_type_of_reasons_hold`.
- AT-W0d: `test_static_all_matches_census_walk` fails when the census walk is patched to skip one package, and when
  one `__all__` gets a name the walk does not see. Lowering a floor with no name removed in the same diff is caught
  by the F10 gate check.
- AT-W0e (HIGH-1): `test_type_closure_is_complete`. Removing `ConfigProblem` from the root (with no exclusion row)
  fails it, because the kept `PipelineConfigError` constructor reaches it. Removing `PhaseEvent` fails it through
  the `ProgressEvent` union in `ProgressSink.on_event`. `test_closure_exclusions_are_reached` fails on a stale row.
- AT-W0f: `test_closure_exclusion_categories_match_scan` consumes section 2 scan output and the section 3 closure edges. For every row require its qualified identity, its stated incoming edge, zero external named or callback consumers, and the category derived from its defining module and role. Use closed category rules independent of the CSV. For `removed-keyword`, prove the only paths disappear with B7. Reject unknown categories, a different category from the same family, and missing scan inputs. At the cross-repo gate, supply the three source heads explicitly. Exercise the same check in engine CI with small source fixtures. Run the full category check against the pinned source trees at W0 and again at the final gate. Seed an aliased private import of `ColumnSeed`, a callback passed through a logger, a dynamic exception lookup, a wrong category on `TableSeed`, and an unrelated same-name enum. The first four must expose misclassification. The unrelated enum must leave the engine result alone.
- AT-Wn (each move slice): for each name, `from decoy_engine import N` raises `ImportError` (parametrized over
  `REMOVED_PUBLIC_NAMES`) and `from decoy_engine.<home> import N` succeeds (`test_moved_names_import_from_home`,
  table of `(name, home)`).
- AT-W7: each deleted object is absent from its home module (`hasattr(home, N)` is false).
- AT-C1: CLI T1 passes on the existing pin. Scan for home imports of kept names already exported by that pin. AT-C2 extends that assertion to every final kept name on the new pin.
- AT-C2: CLI `tests/e2e/run_progress/test_run_progress_events.py` imports `event_to_dict` from
  `decoy_engine.progress`; the full CLI suite passes against the engine stack top.

Mutations the gate runs: re-add one moved name to `__all__` only (AT-W0a fails); keep its import in `__init__.py`
but drop it from `__all__` (AT-W0b fails); delete one `Breaking:` line (signature sentry fails); leave one
frozen-surfaces row (map test fails); point a `type-of:` reason at a wrong kept name (AT-W0c fails); drop the union
expansion from the closure walker (AT-W0e fails); drop the `Raises:` parsing (AT-W0e fails on the `compile_plan` to `PoolCapacityError` edge);
make the census walk skip the public `decoy_engine.fileaccess` package (AT-W0d fails).

## 7. Slices

Order: E-S1a and E-S1b from the batch plan stay first and unchanged. Then W0, then W2 through W6, then W7. C1 can land on the old pin. Test C2 against the stack before merge and land it atomically with the CLI repin. Each W slice touches
`__init__.py`, the guard files and the docs, so W slices stack and rebase in order; one full engine suite on the
stack top (frozen contract is a full-suite trigger), then merge in order.

| Slice | Repo | Content | Names | Est. lines | Depends on |
|---|---|---|---|---|---|
| E-S1a | engine | batch plan B1, B2, B4, B6, B8 | as batch plan | ~280 | none |
| E-S1b | engine | batch plan B3, B5, B7, D12 | as batch plan | ~450 | E-S1a |
| W0 | engine | publish the 28 W0 inventory additions by identity through owning package APIs; document their frozen root paths; add the `ROOT_SURFACE` mapping and behaviors 2, 3 and 9; `CLOSURE_EXCLUSIONS` seeded from the exclusions CSV; `test_static_all_matches_census_walk`; `BundlePool` hint fix; `test_moved_names_import_from_home` scaffold | 28 added | ~380 | E-S1b |
| W2 | engine | SDK root re-exports (D6): `CAP_DRY_RUN`, `CAP_INTROSPECTION`, `CAP_MULTIPART`, `CAP_RESUMABLE`, `CAP_SIGNED_URL`, `CAP_STREAMING`, `SDK_VERSION`, `CheckResult`, `ConnectorConfig`, `FileMeta`, `FileSink`, `FileSource`, `WriteResult` | 13 | ~150 | W0 |
| W3 | engine | progress and context helpers: `CallbackSink`, `StructuredEventsSink`, `emit_lineage`, `emit_step`, `emit_throughput_sample`, `event_to_dict` | 6 | ~110 | W0, E-S1b |
| W4 | engine | providers and generation: `AdapterError`, `CardinalityMode`, `CompositeAdapter`, `CompositeGenerator`, `PoolAdapter`, `PoolBuilder`, `PoolSampler`, `generate_tables`, `get_default_pool_cache`, `load_custom_providers`, `register_faker_list_provider`, `register_faker_provider`, `register_faker_provider_v2`, `unregister_faker_provider` | 14 | ~180 | W0 |
| W5 | engine | keys, determinism, release: `RELEASE_PHASE`, `ReleasePhase`, `is_pre_ga`, `DeterminismError`, `Domain`, `IdentityDomain`, `derive`, `derive_index`, `derive_value`, `SeedKeyProvider`, `WeakMaskSecret`, the five D3 secret names, `SecretProviderError`, `KeyedColumn`, `keyed_columns_for_config`; root docstring rewrite (D4) | 19 | ~230 | W0, E-S1b |
| W6 | engine | scan, plan, validation, errors: `CompositeCoherenceReport`, `ConfigRuleError`, `DistinctCount`, `FkValidityReport`, `NullCount`, `PlanCheckError`, `PlanValidationResult`, `PostValidationRunner`, `QualitySummary`, `ValidationError`, `check_columns_declared`, `declared_columns`, `is_value_sensitive`, `reasons_from_report`, `redact_profile_dict`, `source_columns`, `validate_config`, `validate_plan` | 18 | ~220 | W0 |
| W7 | engine | deletes, root and object: `register_secret_provider`, `ConnectorAuthError` (D5), their home `__all__` rows and own tests; final floors (D1); `pending:` assert on | 2 | ~200 | W0, W2 to W6 |
| C1 | CLI | the home-path imports of names already exported on 0.28.3 go through the root: `_mask_secret.py:130`, `cli/preflight.py:421,453`, `cli/library/_read.py:156,160`, `_store.py:88,169,176,320,324`, `_fsck.py:211,290,376`, `_export.py:79`, `_exporting.py:126`, `cli/exit_codes.py:152,236`, `cli/run/_errors.py:112,183`, `cli/scanning/_engine_call.py:20`, `cli/io/_lazy.py:25`, `cli/run/_result.py:100`, `cli/demo.py:230` | 0 | ~60 | none (works on 0.28.3) |
| C2 | CLI | In the repin diff, move `PipelineConfigError`, `PlanCompileError`, `Profile`, `ConfigRef`, `Links`, `NativeRoute` and `TableDelivery` imports to the root at every inventory site. Move the `event_to_dict` test import to `decoy_engine.progress`. Scan source and tests again and run the full CLI suite on the paired heads. | 7 new root targets | ~40 | C1 and the engine release with W0 through W7 |

Platform: no slice. Section 10 lists the repin notes.

Before a builder starts W7, it re-runs the delete-rule search (section 2) on its head. Any reader found turns the
name into a move in that slice.

## 8. In-step edits per slice

Every removal slice, in the same diff:
- `src/decoy_engine/__init__.py`: drop the import and the `__all__` entry; fix the module docstring list.
- Drop removed keys in the W0 release sentry. In `tests/unit/test_public_api.py`, add each name to `REMOVED_PUBLIC_NAMES`; add
  `(name, home)` rows to `test_moved_names_import_from_home` (moves only). W7 deletes
  `test_connector_auth_error_subclasses_connector_error` (line 386) and the presence rows for its deletes.
- `docs/frozen-surfaces.md`: drop the names from their "Public names (contract 3.4)" row; W2 and W4 drop the
  un-prefixed names from the experimental table (the `sdk.` names stay).
- `src/decoy_engine/contracts/stability.py`: an `EXPERIMENTAL_OBJECTS` row goes only if no walked public path still
  exports the object (expected: none go in W4, since `decoy_engine.providers` still exports the faker functions).
  `TIER_EXCEPTIONS` and `PACKAGE_TIERS` unchanged.
- `tests/sentry/release/test_public_census.py`: W2 moves the root `FileSource`, `FileSink`, `ConnectorConfig`,
  `SDK_VERSION`, `CAP_STREAMING` asserts (line 40) to the `sdk` path; W4 moves line 42 (`register_faker_provider`)
  to `decoy_engine.providers`. Line 49 (`ConfigError`, `ConnectorError` FROZEN at root and `sdk`) stays: both are
  kept. Floors per D1.
- `tests/sentry/release/test_public_signatures.py`: `HEAD_FLOOR` per D1. One `changelog.d/<slice>.md` with
  `Breaking:` lines naming each removed object in backticks.
- `CHANGELOG.md` "Removed" entry. `docs/compatibility-contract.md` §3.4 and §3.6 text where it names a removed root
  name.
- Tests, scripts, examples and testflight files that import a moved name through the root switch to the home
  module. Use the per-name inventory and rerun the scan on each head.

Slice-specific edits:
- W0, contract §3.1 (MEDIUM-2): after the paragraph at `docs/compatibility-contract.md:434-462`, add one sentence:
  the root exports `RunResult`, `RunResultRead`, `RUN_RESULT_SCHEMA` and `ScanSetCore` as part of this artifact
  contract, so they stay at `decoy_engine` while the formats are frozen; `ScanSetCoreRead` stays at
  `decoy_engine.profiling`.
- W5, release names (LOW-1):
  - `docs/qa/18-evidence-reasons-compat.md:44` (EVID-10): read `decoy_engine.release.RELEASE_PHASE` and
    `decoy_engine.release.is_pre_ga()`.
  - `tests/integration/compat_corpus/test_compat_corpus.py:8` and `tests/integration/compat_corpus/regenerate.py:14`
    docstrings: `decoy_engine.release.RELEASE_PHASE`.
  - Engine `CLAUDE.md:23`: `decoy_engine.release.RELEASE_PHASE`. `CODEMAP.md:89` and `_MAP.md:54` already name
    `release.py`; no edit.
  - Root `__init__.py` docstring paragraph that says the platform reads `RELEASE_PHASE`: rewrite to name
    `decoy_engine.release`.
  - Platform `docs/architecture/engine.md:140` and ADR
    `docs/architecture/adr/platform/0005-mechanical-enforcement-of-methodology.md`: repin notes (section 10), since
    the platform is parked and gets no edit here.
- W5 records the two keyed-column root moves in the changelog and adds a dated home-path correction at `docs/compatibility-contract.md:1344-1350`. Preserve the implementation, package exports and all tests in `tests/secret_providers/test_keyed_columns.py`.
- W6 records a platform repin edit for `docs/guides/engine-capabilities.md:30`: give `ValidationError` its home path `decoy_engine.errors.ValidationError`.
- W7 records a platform repin edit for `docs/guides/engine-capabilities.md:30`: remove `ConnectorAuthError` from the exceptions row.
- W7, `ConnectorAuthError`: drop its row at `tests/sentry/test_reason_registry.py:560` and its `errors.py:577`
  `__all__` row.

The W0 PR body lists **each** exclusion outside the config and contract groups for owner review. Print the qualified name, incoming edge, category and reason for every such row. Exempt only `config-model`, `contract-scan` and `contract-run-result`. Generate this list from the actual W0 exclusions and check the exact set. Counts or a link to the CSV alone do not satisfy the gate.

### Placement

| New file | Location and neighbor | CODEMAP rule |
|---|---|---|
| `test_root_surface.py` | Engine `tests/sentry/release/`, beside `test_public_census.py`. Put root and closure assertions here. | Engine CODEMAP line 295, release sentries |
| `_root_surface.py` | Same directory, beside `_census.py`. Own the root reasons and exclusion registry here. Generate the initial data from the reviewed CSVs. | Engine CODEMAP line 295, sentry helpers |
| `_surface_scan.py` | Same directory, beside `_census.py`. One scanner feeds the consumer, category and repin checks. | Engine CODEMAP line 295, sentry helpers |
| Per-slice fragment | Engine `changelog.d/<slice>.md`, beside its README | Engine CODEMAP line 302, changelog fragments |

Use the existing `_census.py` literal parser and tier rules. For an addition available only in its private defining module, expose that same object from its owning package first. Verify root, owner and old consumer paths refer to the identical object. Document added owner exports and run the import-layer and frozen-surface guards. Preserve existing caps.

W0 seeds `ROOT_SURFACE` with every name still in `__all__` on its head; names that later slices remove carry the
reason `pending:<slice>`, so the table is honest while the stack lands. W7 turns on the assert that no `pending:`
reason remains.

## 9. Test depth and gates

- T0 per edit; T1 impact selection per commit.
- T2 at the gate on the exact head: `tests/unit/test_public_api.py`, `tests/sentry/release/`,
  `tests/sentry/test_exception_hierarchy.py`, `tests/sentry/test_reason_registry.py`,
  `tests/unit/execution/test_r3_public_signature_freeze.py`, the docs build with `-W`, plus the section 6 mutations.
- Full engine suite once on the stack top (frozen-contract trigger), diffed against the saved main baseline.
- CLI compatibility gate: C1 runs CLI T1. Before the W stack merges, the gate installs the engine stack top into a scratch
  CLI venv on top of C1 and C2, and runs the full CLI suite there, diffed against the CLI main baseline. A new red
  blocks the engine merge.
- Commit subjects follow Conventional Commits, for example `refactor(api): drop progress helpers from the root`,
  final line `cam`.

## 10. After merge

Mark the post-1.0 B rows done as E-S1a and E-S1b already plan. Close 24zj after W7 merges, the paired CLI gate passes, and the root has no `pending:` reason.

Platform repin notes (MEDIUM-3, added to the platform repin list):
- Use every platform source site in the inventory. Retarget the existing kept imports and all newly exported platform types on the new pin. This includes config and plan errors, layout and generation models, the file-access interfaces, plan/seed models, detector spec, token writer and lazy source. In `api/jobs/fixed_width_output.py:240-242`, resolve both exceptions from the root module already loaded in that call. Verify old and new objects are identical and run platform import, guard and job tests before releasing the repin. Keep the scheduler enum in the ORM and keep the structural logger wiring.
- Apply both W6 and W7 corrections to platform `docs/guides/engine-capabilities.md:30` at repin.
- Tests that import a moved name from the root:
  - `tests/test_custom_faker_providers.py:270,346`: `unregister_faker_provider` (and `register_faker_provider` if
    imported there) from `decoy_engine.providers`. Rechecked: both move together, so the pair stays together at
    the home path; no platform src reads either.
  - `tests/test_health.py:40`: `validate_config` from `decoy_engine.validation`. Rechecked: test-only, so move.
  - `tests/test_job_estimate_schema.py:278`: `JobEstimate` stays at the root (keep-closure of `estimate_job`); no
    edit.
- Docs: `docs/architecture/engine.md:140` and ADR 0005 name `decoy_engine.RELEASE_PHASE`; change to
  `decoy_engine.release.RELEASE_PHASE`.

## 11. Round 1 changes

Round 1 added the runtime closure, reader checks, the profile writer pairing, static census verification, CLI integration gate and platform repin notes. Sections 2 through 10 give the current decisions.

## Round 2 changes

| Finding | Fix and verification |
|---|---|
| V1 HIGH-A | Rechecked 185 qualified types. W0 exports 26 named imports and the dynamically read writer error. The requested engine publication enum has an independent closure edge. The other 157 rows have categories checked by AT-W0f. C1, C2 and the platform repin use the same source evidence. |
| V1 HIGH-B | W5 moves both keyed-column names and keeps their oracle. The shared iterator counts as a source reader. W7 deletes only the registration helper and the unused auth error. |
| V1 HIGH-C | The scan covers all engine protocols and traces structural matches to engine call sites. W3 keeps `StructuredEvents` for `platform:api/persistence/logger.py`. |
| V2-LOG / DESIGN MEDIUM-1 | D1 derives the expected package set from the file system and compares it with the census. AT-W0d removes a package from the observed walk. |
| V2-LOG MEDIUM-2 | The W0 PR body enumerates every surviving exclusion outside the three config and contract categories for owner review. |
| V2-LOG LOW-1 | The W6 and W7 edit lists name the platform capabilities guide and specify both changes at repin. |

The inventory accounts for 258 decisions. The final root contains 181 names. The 77 original names that leave it comprise 70 moves and seven deletes.
