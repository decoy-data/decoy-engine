# Frozen surfaces

Status: current

This is the list of engine surfaces that freeze at the D-4 engine release that CLI 1.0.0 pins (see
the REL-GATE plan). Each row names the code that owns a surface and the test or snapshot that turns red
when it changes. The rules for changing a frozen surface are in the
[compatibility contract](compatibility-contract.md); a pull request that touches one carries its
section-9 checklist.

`tests/sentry/release/test_frozen_surface_map.py` keeps this page complete. It reads the tag block
of contract 3.1 and the names in `decoy_engine.__all__` and `decoy_engine.sdk.__all__`, and fails
when an item has no row, has two, or a row names a path that does not exist. A surface with no
pinning test says `accepted-known-limit: <id>`, and the id is listed under
[Known limits](#known-limits); the release readiness record repeats each one.

## Format tags (contract 3.1, 3.2)

| Surface | Completeness source | Owning code | Pinning test or snapshot |
|---|---|---|---|
| `distribution-snapshot/v1` | contract 3.1 | `src/decoy_engine/quality/snapshot.py` | `tests/snapshots/test_distribution_snapshot_baseline.py`, `tests/integration/compat_corpus/test_compat_corpus.py` |
| `decoy-vault/v2` | contract 3.1, 3.2 | `src/decoy_engine/vault.py` | `tests/unit/test_vault.py`, `tests/integration/compat_corpus/test_compat_corpus.py` |
| `vault-key/v1` | contract 3.1, 3.2 | `src/decoy_engine/vault.py` | `tests/unit/test_vault.py`, `tests/integration/compat_corpus/test_compat_corpus.py` |
| `ff1-key/v1` | contract 3.1 | `src/decoy_engine/transforms/fpe.py` | `tests/native/test_determinism_protocol.py`, `tests/unit/execution/test_fpe_strategy.py` |
| `quality-report/v1` | contract 3.1 | `src/decoy_engine/quality/report.py` | `tests/snapshots/test_quality_report_baseline.py` |
| `synth-report/v1` | contract 3.1 | `src/decoy_engine/quality/synth_report.py` | `tests/unit/quality/test_synth_report_characterization.py` |
| `quality-diagnostic/v1` | contract 3.1 | `src/decoy_engine/quality/diagnostic.py` | `tests/snapshots/test_quality_diagnostic_baseline.py` |
| `quality-fidelity/v1` | contract 3.1 | `src/decoy_engine/quality/fidelity.py` | `tests/snapshots/test_quality_fidelity_baseline.py` |
| `quality-policy/v1` | contract 3.1 | `src/decoy_engine/quality/policy.py` | `tests/snapshots/test_quality_policy_baseline.py` |
| `quality-shape-fidelity/v1` | contract 3.1 | `src/decoy_engine/quality/shape_fidelity.py` | `tests/snapshots/test_quality_shape_fidelity_baseline.py` |
| `post-scan-integrity/v3` | contract 3.1 | `src/decoy_engine/verification/postmask/types.py` | `tests/unit/detection_verification/test_postmask_runner.py` |
| `name-hints/v1` | contract 3.1 | `src/decoy_engine/detection/name_hints/v1/manifest.yaml` | `tests/snapshots/test_name_hints_baseline.py` |
| `ssn/v1` | contract 3.1 | `src/decoy_engine/providers_v2/identifiers/_ssn.py` | `tests/unit/providers_v2/identifiers/test_identifiers.py`, `accepted-known-limit: RGF1-KL-1` |
| `npi/v1` | contract 3.1 | `src/decoy_engine/providers_v2/identifiers/_npi.py` | `tests/unit/providers_v2/identifiers/test_identifiers.py`, `accepted-known-limit: RGF1-KL-1` |
| `pan/v1` | contract 3.1 | `src/decoy_engine/providers_v2/identifiers/_pan.py` | `tests/unit/providers_v2/identifiers/test_identifiers.py`, `tests/unit/providers_v2/identifiers/test_pan.py`, `accepted-known-limit: RGF1-KL-1` |
| `iban/v1` | contract 3.1 | `src/decoy_engine/providers_v2/identifiers/_iban.py` | `tests/unit/providers_v2/identifiers/test_identifiers.py`, `tests/unit/providers_v2/identifiers/test_iban.py`, `accepted-known-limit: RGF1-KL-1` |
| `ein/v1` | contract 3.1 | `src/decoy_engine/providers_v2/identifiers/_ein.py` | `tests/unit/providers_v2/identifiers/test_identifiers.py`, `accepted-known-limit: RGF1-KL-1` |
| `mrn/v1` | contract 3.1 | `src/decoy_engine/providers_v2/identifiers/_mrn.py` | `tests/unit/providers_v2/identifiers/test_identifiers.py`, `accepted-known-limit: RGF1-KL-1` |
| `ndc/v1` | contract 3.1 | `src/decoy_engine/providers_v2/identifiers/_ndc.py` | `tests/unit/providers_v2/identifiers/test_identifiers.py`, `accepted-known-limit: RGF1-KL-1` |
| `icd10/v1` | contract 3.1 | `src/decoy_engine/providers_v2/identifiers/_icd10.py` | `tests/unit/providers_v2/identifiers/test_identifiers.py`, `tests/unit/providers_v2/identifiers/test_icd10.py`, `accepted-known-limit: RGF1-KL-1` |
| `cusip/v1` | contract 3.1 | `src/decoy_engine/providers_v2/identifiers/_cusip.py` | `tests/unit/providers_v2/identifiers/test_identifiers.py`, `tests/unit/providers_v2/identifiers/test_cusip.py`, `accepted-known-limit: RGF1-KL-1` |
| `address/v1` | contract 3.1 | `src/decoy_engine/generation/composite/_address.py` | `tests/unit/generation/composite/test_address.py`, `accepted-known-limit: RGF1-KL-1` |
| `locality/v1` | contract 3.1 | `src/decoy_engine/generation/composite/_city_state_zip.py` | `tests/unit/generation/composite/test_composite.py`, `accepted-known-limit: RGF1-KL-1` |
| `person/v1` | contract 3.1 | `src/decoy_engine/generation/composite/_person.py` | `tests/unit/generation/composite/test_person.py`, `accepted-known-limit: RGF1-KL-1` |
| `provider/v1` | contract 3.1 | `src/decoy_engine/generation/composite/_provider.py` | `tests/unit/generation/composite/test_provider.py`, `accepted-known-limit: RGF1-KL-1` |
| `composite/v1` | contract 3.1 | `src/decoy_engine/generation/composite/_generator.py` | `tests/unit/generation/composite/test_composite.py`, `accepted-known-limit: RGF1-KL-1` |
| `custom/v1` | contract 3.1 | `src/decoy_engine/generation/composite/_custom.py` | `tests/unit/generation/composite/test_custom.py`, `accepted-known-limit: RGF1-KL-1` |
| `subset-manifest/v1` | contract 3.1 | `src/decoy_engine/subset/_manifest.py` | `tests/integration/subset/test_manifest.py` |
| `decoy-run-result/v1` | contract 3.1 | `src/decoy_engine/run_result/_model.py` | `tests/unit/run_result/test_model_shapes.py`, `tests/unit/run_result/test_model.py`, `tests/integration/compat_corpus/run_result/`, `tests/snapshots/frozen_schemas/run-result.schema.json` |
| `decoy-record/v1` | contract 3.1 | `src/decoy_engine/records/_envelope.py` | `tests/unit/records/test_corpus.py`, `tests/integration/compat_corpus/records/` |
| `sample-run/v1` | contract 3.1 | `src/decoy_engine/records/_kinds.py` | `tests/unit/records/test_corpus.py`, `tests/unit/records/test_kinds.py` |
| `decoy-library-export/v1` | contract 3.1 | `src/decoy_engine/records/_export.py` | `tests/unit/records/test_corpus.py`, `tests/unit/records/test_export.py` |
| `decoy-job-log/v1` | contract 3.1 | `src/decoy_engine/records/_joblog.py` | `tests/unit/records/test_corpus.py`, `tests/unit/records/test_joblog.py` |
| `scan-set/v1` | contract 3.1 | `src/decoy_engine/profiling/scan_set.py` | `tests/unit/profiling/test_scan_set.py` |
| `scan-diff/v1` | contract 3.1 | `src/decoy_engine/profiling/scan_diff.py` | `tests/unit/profiling/test_scan_diff.py`, `tests/integration/compat_corpus/scan_diff/` |
| `decoy-resume-run/v1` | contract 3.1 | `src/decoy_engine/delivery/resume/_records.py` | `tests/unit/delivery/resume/test_records.py`, `tests/integration/compat_corpus/resume/resume-run-v1.json` |
| `decoy-resume-table/v1` | contract 3.1 | `src/decoy_engine/delivery/resume/_records.py` | `tests/unit/delivery/resume/test_records.py`, `tests/integration/compat_corpus/resume/resume-table-v1.json` |
| `lock/v1` | contract 3.1 | `src/decoy_engine/support/_runtime_lock.py` | `tests/unit/support/test_runtime_lock.py`, `tests/integration/compat_corpus/runtime-lock/lock-v1.json` |

## Public names (contract 3.4)

`tests/unit/test_public_api.py` (`test_all_lists_every_public_name`) holds `decoy_engine.__all__`
to its expected set. Names exported again by `decoy_engine.sdk` are listed as `sdk.<name>`; this
page's sentry is what holds `sdk.__all__`, because a name added to or dropped from it fails the
row check. Both pin that a name exists, not its signature or fields; rows that cite `RGF1-KL-4`
have nothing more.

| Surface | Completeness source | Owning code | Pinning test or snapshot |
|---|---|---|---|
| Run entry point: `ExecutionResult`, `run_pipeline` | `decoy_engine.__all__` | `src/decoy_engine/execution/`, `src/decoy_engine/__init__.py` | `tests/unit/execution/test_r3_public_signature_freeze.py`, `tests/unit/test_public_api.py` |
| Pipeline config model: `PipelineConfig` | `decoy_engine.__all__` | `src/decoy_engine/config/` | `tests/snapshots/test_frozen_schemas.py`, `tests/snapshots/frozen_schemas/pipeline-config.schema.json`, `tests/unit/test_public_api.py` |
| Run result: `RUN_RESULT_SCHEMA`, `RunResult`, `RunResultRead`, `derive_outcome` | `decoy_engine.__all__` | `src/decoy_engine/run_result/` | `tests/snapshots/test_frozen_schemas.py`, `tests/unit/run_result/test_model_shapes.py`, `tests/unit/run_result/test_outcome.py`, `tests/unit/test_public_api.py` |
| Connector SDK: `CheckResult`, `ConnectorConfig`, `FileMeta`, `FileSink`, `FileSource`, `PermanentError`, `TransientError`, `WriteResult`, `sdk.CAP_DRY_RUN`, `sdk.CAP_INTROSPECTION`, `sdk.CAP_MULTIPART`, `sdk.CAP_RESUMABLE`, `sdk.CAP_SIGNED_URL`, `sdk.CAP_STREAMING`, `sdk.CheckResult`, `sdk.ConfigError`, `sdk.ConnectorConfig`, `sdk.ConnectorError`, `sdk.FileMeta`, `sdk.FileSink`, `sdk.FileSource`, `sdk.PermanentError`, `sdk.SDK_VERSION`, `sdk.TransientError`, `sdk.WriteResult` | `decoy_engine.__all__`, `decoy_engine.sdk.__all__` | `src/decoy_engine/sdk.py` | `tests/unit/test_sdk_smoke.py`, `tests/unit/test_public_api.py`, `accepted-known-limit: RGF1-KL-4` |
| Errors: `ConfigError`, `ConfigRuleError`, `ConnectorAuthError`, `ConnectorError`, `DecoyError`, `FixedWidthParseError`, `FlagPauseSignal`, `LicenseError`, `LicenseExpiredError`, `PipelineValidationError`, `PostScanBlockedError`, `ValidationError` | `decoy_engine.__all__` | `src/decoy_engine/errors.py`, `src/decoy_engine/verification/postmask/_blocked.py` | `tests/sentry/test_exception_hierarchy.py`, `tests/unit/detection_verification/postscan/test_blocked.py`, `tests/unit/test_public_api.py`, `accepted-known-limit: RGF1-KL-4` |
| Context and logging: `ExecutionContext`, `Logger`, `StructuredEvents`, `TelemetryClient`, `emit_fidelity`, `emit_lineage`, `emit_quarantine`, `emit_step`, `emit_throughput_sample`, `make_key_resolver` | `decoy_engine.__all__` | `src/decoy_engine/context.py` | `tests/unit/test_public_api.py`, `accepted-known-limit: RGF1-KL-4` |
| Constants: `CAP_DRY_RUN`, `CAP_INTROSPECTION`, `CAP_MULTIPART`, `CAP_RESUMABLE`, `CAP_SIGNED_URL`, `CAP_STREAMING`, `FILE_SOURCE_PATH_FIELDS`, `RELEASE_PHASE`, `ReleasePhase`, `SDK_VERSION`, `SEED_PROTOCOL_VERSION` | `decoy_engine.__all__` | `src/decoy_engine/sdk.py`, `src/decoy_engine/release.py`, `src/decoy_engine/determinism/`, `src/decoy_engine/config/` | `tests/unit/determinism/test_derive_vectors.py`, `tests/unit/test_public_api.py`, `accepted-known-limit: RGF1-KL-4` |
| Execution: `CapacityEstimate`, `CapacityVerdict`, `ExecutionAdapter`, `ExecutionError`, `ExecutionEvent`, `JobEstimate`, `NativeCompanionStatus`, `PandasExecutionAdapter`, `StrategyError`, `StrategyInfo`, `StrategyOption`, `apply_table_transforms`, `detect_usable_cpus`, `estimate_job`, `estimate_job_capacity`, `get_default_executor`, `native_companion_status`, `resolve_conservative_ooc_budget_bytes`, `route_summary`, `run_mask_chunked`, `run_mask_pipeline_chunked`, `select_execution_adapter`, `strategy_catalog` | `decoy_engine.__all__` | `src/decoy_engine/execution/` | `tests/unit/test_public_api.py`, `accepted-known-limit: RGF1-KL-4` |
| Generation: `CardinalityMode`, `CompositeAdapter`, `CompositeCustom`, `CompositeError`, `CompositeGenerator`, `CompositePerson`, `CompositeProvider`, `GenerationError`, `PoolAdapter`, `PoolBuilder`, `PoolCapacityError`, `PoolSampler`, `QualityWarning`, `ValuePool`, `composite_address`, `composite_custom`, `composite_name_email`, `composite_person`, `composite_provider`, `generate_tables`, `generated_table_to_pandas`, `get_default_pool_cache` | `decoy_engine.__all__` | `src/decoy_engine/generation/` | `tests/unit/test_public_api.py`, `accepted-known-limit: RGF1-KL-4` |
| Scan, profile and detection: `ColumnProfile`, `DeclarationRequest`, `DetectorMatch`, `DiscoveryResult`, `DiscoverySqlError`, `FieldStats`, `ModelHit`, `ModelRef`, `ModelStatus`, `ModelUnavailableError`, `PreparedDeclaredSources`, `ScanSet`, `ScanSetCore`, `SentinelFlag`, `TableScan`, `check_columns_declared`, `classifier_status`, `declared_columns`, `distribution_snapshot_document`, `is_value_sensitive`, `load_detectors`, `ner_status`, `prepare_declared_sources`, `profile_columns`, `profile_document`, `read_csv_source`, `read_fixed_width`, `redact_profile_dict`, `resolve_csv_dialect`, `run_discovery_sql`, `scan_set_to_dict`, `scan_sources`, `snapshot_joint_warnings`, `source_columns`, `write_fixed_width` | `decoy_engine.__all__` | `src/decoy_engine/profiling/`, `src/decoy_engine/profile/`, `src/decoy_engine/detection/`, `src/decoy_engine/data_discovery.py` | `tests/unit/test_public_api.py`, `accepted-known-limit: RGF1-KL-4` |
| Progress events: `CallbackSink`, `CheckpointEvent`, `CheckpointInfo`, `PhaseEvent`, `ProgressSink`, `PublicationInfo`, `RateSample`, `RetryEvent`, `RetryInfo`, `RouteEvent`, `StructuredEventsSink`, `TerminalEvent`, `WarningEvent`, `event_to_dict`, `event_to_legacy_dict` | `decoy_engine.__all__` | `src/decoy_engine/_progress_events.py`, `src/decoy_engine/progress.py` | `tests/unit/test_public_api.py`, `accepted-known-limit: RGF1-KL-4` |
| Keys, secrets, vault and determinism: `DeterminismError`, `Domain`, `IdentityDomain`, `KeyProvider`, `KeyedColumn`, `KeyedStrategyRequiresSecret`, `MaskSecretError`, `MissingMaskSecret`, `SecretCachePolicy`, `SecretDescriptor`, `SecretKeyProvider`, `SecretProvider`, `SecretProviderError`, `SecretProviderRegistry`, `SecretRef`, `SeedKeyProvider`, `UnmaskColumnReport`, `UnmaskResult`, `VaultError`, `VaultWriter`, `WeakMaskSecret`, `derive`, `derive_index`, `derive_value`, `keyed_columns_for_config`, `load_vault`, `open_protected_dir`, `protected_scratch_dir`, `register_secret_provider`, `unmask_pipeline`, `vault_writer_for_config` | `decoy_engine.__all__` | `src/decoy_engine/keyprovider.py`, `src/decoy_engine/secret_providers/`, `src/decoy_engine/vault.py`, `src/decoy_engine/unmask.py`, `src/decoy_engine/determinism/`, `src/decoy_engine/fileaccess/` | `tests/unit/test_public_api.py`, `accepted-known-limit: RGF1-KL-4` |
| Config helpers, plan, validation and relationships: `CompositeCoherenceReport`, `ConfigProblem`, `CsvDialect`, `Dismissal`, `DistinctCount`, `FkValidityReport`, `NamespaceBinding`, `NamespaceConfigError`, `NamespaceRegistry`, `NullCount`, `OrphanPolicy`, `PlanCheckError`, `PlanValidationResult`, `PostScanRouteError`, `PostValidationRunner`, `PreScanConfig`, `QualitySummary`, `RelationshipEdge`, `RelationshipGraph`, `VALIDATION_CODES`, `ValidationMessage`, `ValidationResult`, `build_namespace_registry`, `build_relationship_graph`, `check_orphan_fk_policy_completeness`, `classify_table_kinds`, `compile_plan`, `is_valid_pipeline_name`, `job_seed_for_config`, `parse_pipeline_config`, `pipeline_config_hash`, `run_config_only_checks`, `validate_config`, `validate_plan` | `decoy_engine.__all__` | `src/decoy_engine/config/`, `src/decoy_engine/plan/`, `src/decoy_engine/validation/`, `src/decoy_engine/validation_result.py`, `src/decoy_engine/relationships/`, `src/decoy_engine/safe_output/`, `src/decoy_engine/verification/` | `tests/unit/test_public_api.py`, `accepted-known-limit: RGF1-KL-4` |
| Records, reasons and release phase: `DecodedRecord`, `OpaqueRecord`, `ReasonContext`, `ReasonRecord`, `RecordError`, `RecordNeedsNewer`, `is_pre_ga`, `reason_from_exception`, `reasons_from_report` | `decoy_engine.__all__` | `src/decoy_engine/records/`, `src/decoy_engine/reasons/`, `src/decoy_engine/reason_adapter.py`, `src/decoy_engine/release.py` | `tests/unit/test_public_api.py`, `accepted-known-limit: RGF1-KL-4` |
| Providers: `AdapterError`, `BackendAdapter`, `CapabilityMatrix`, `ProviderError`, `ProviderRegistry`, `ProviderSpec`, `atomic_swap_db_providers`, `get_default_registry`, `list_generate_faker_providers`, `load_custom_providers`, `register_faker_list_provider`, `register_faker_provider`, `register_faker_provider_v2`, `unregister_faker_provider` | `decoy_engine.__all__` | `src/decoy_engine/providers_v2/`, `src/decoy_engine/providers.py` | `tests/unit/test_public_api.py`, `accepted-known-limit: RGF1-KL-4` |

## Other frozen surfaces

| Surface | Completeness source | Owning code | Pinning test or snapshot |
|---|---|---|---|
| Pipeline YAML schema | design note 3 of the REL-GATE plan | `src/decoy_engine/config/` | `tests/snapshots/test_frozen_schemas.py`, `tests/snapshots/frozen_schemas/pipeline-config.schema.json` |
| Run-result schema | design note 3 of the REL-GATE plan | `src/decoy_engine/run_result/` | `tests/snapshots/test_frozen_schemas.py`, `tests/snapshots/frozen_schemas/run-result.schema.json` |
| Determinism: same input and seed give the same bytes | contract 3.3 | `src/decoy_engine/determinism/` | `tests/unit/determinism/test_derive_vectors.py`, `tests/unit/determinism/test_hkdf.py`, `tests/native/test_draw_site_providers_golden.py`, `tests/native/test_determinism_goldens.py`, `accepted-known-limit: RGF1-KL-2` |
| Disguise registry (every disguise spec) | contract 3.5 | `src/decoy_engine/disguises/` | `tests/unit/test_disguises_loader.py`, `accepted-known-limit: RGF1-KL-3` |
| Reason registry | contract 3.4 | `src/decoy_engine/reasons/` | `tests/unit/test_reason_registry.py`, `tests/sentry/test_reason_baseline_frozen.py`, `tests/unit/test_reason_release_pin.py` |
| Engine version literal | `pyproject.toml` | `src/decoy_engine/release.py` | `tests/unit/test_version_agreement.py` |

The schema snapshots pin field names, types and declared defaults; descriptions (the model
docstrings) are left out, so a docstring edit does not touch them. Validators and runtime defaults chosen in code
(such as the ones `is_pre_ga()` switches) do not appear in a schema; their unit tests pin them.
Regenerate the snapshots with `python scripts/release/frozen_schemas.py --write` only for a
reviewed change; `--check` prints the file and the first differing JSON pointer, never a value.

## Known limits

| Id | Surface | Limit |
|---|---|---|
| `RGF1-KL-1` | identifier and composite generator tags | The unit tests check format and validity, not known outputs, so a change to what a seed produces under the same `/v1` tag would pass. |
| `RGF1-KL-2` | determinism golden files | `tests/snapshots/golden/mask_faker_seeded`, `mask_hash_only` and `mask_redact` have no reader since the V1 graph runner and its test were deleted (commit `b9b73e19e`). The files stay. The row's tests pin the derivation (a reference vector and HKDF), each draw site's provider output by stored digest, and the shipped handlers' output against those providers for the sites in `expected_sites` of `tests/native/test_determinism_goldens.py`. The other provider sites (for example `mask.tokenize`, `mask.formula`, `gen.lookup`) are pinned only at the provider: no test checks their shipped code against it. `tests/integration/golden/test_determinism_invariants.py` only compares two runs of the current code. |
| `RGF1-KL-3` | disguise registry | No test refuses an edit to a released disguise version. The loader tests pin the dated version field and the bundle set only. |
| `RGF1-KL-4` | public names | Signatures and fields are not pinned except where a row names a signature or shape test. |
