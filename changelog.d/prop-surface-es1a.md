Breaking: `TelemetryClient`, `ExecutionEvent` and `event_to_legacy_dict` are removed from the public surface; `ExecutionContext` loses its `telemetry` parameter, so its positional parameters `resolve_connector`, `derive_key`, `pipeline_derive_key`, `captured_outputs`, `pool_resolver`, `column_relationships` and `instance_default_locale` move up one (pass them by keyword)

### Removed (unused root names, PROP-SURFACE E-S1a, 2026-11-25)

The root `decoy_engine` no longer exports `TelemetryClient`, `ExecutionEvent` and `event_to_legacy_dict`. `ExecutionContext` loses its `telemetry` field and parameter. Use `event_to_dict` for progress events.

The 21 top-level bindings that the F9 trim kept outside `__all__` are gone: `BundlePool`, `CompositeAddress`, `PoolCache`, `composite_city_state_zip`, the `Ein`, `Mrn`, `Ndc`, `Npi` and `Ssn` adapter, domain and validator names, `IdentifierError` and `IdentifierFormatError`. Import them from `decoy_engine.identifiers`, `decoy_engine.generation.pool` or `decoy_engine.generation.composite`.

`decoy_engine.internal.crypto.deterministic_hash` and the `FK_SELF_REFERENCE` alias on the validation codes are deleted. The reason code `fk.self_reference` stays.
