Breaking: removed the public names `LicenseError`, `LicenseExpiredError`, `FlagPauseSignal`, `get_default_executor` and `VALIDATION_CODES` from `decoy_engine`; use `decoy_engine.reasons.config` for codes and `select_execution_adapter` for the adapter

### Removed (dead public names, FREEZE-SURFACE E-DEAD, 2026-11-22)

Five names had no caller in the engine. `LicenseError`, `LicenseExpiredError` and `FlagPauseSignal` are deleted. `get_default_executor` and its cache are deleted. `VALIDATION_CODES` leaves `decoy_engine.__all__`; the internal `validation_result.CODES` stays for its internal users. The `run_paused` reason code is unchanged.
