### Changed (experimental tier and public census, freeze batch X0, 2026-11-18)

The compatibility contract gets section 3.6. Every public engine name now has one tier: frozen,
experimental or documented internal. These names are experimental and may change in any minor
release: the connector SDK objects in `decoy_engine.sdk` (`FileSource`, `FileSink`, `ConnectorConfig`,
`FileMeta`, `CheckResult`, `WriteResult`, `TransientError`, `PermanentError`), `SDK_VERSION`, the
`CAP_*` flags, and the provider registration functions (`register_faker_provider`,
`register_faker_provider_v2`, `register_faker_list_provider`, `unregister_faker_provider`,
`load_custom_providers`, `atomic_swap_db_providers`). Their docstrings start with `Experimental:`.
`ConfigError` and `ConnectorError` stay frozen. No name is removed or renamed. The registry is
`decoy_engine.contracts.stability`, and new sentries check it against the exports and the map.
