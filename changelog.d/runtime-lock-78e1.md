### Added (runtime lock envelope, 78-E1, 2026-11-16)

`decoy_engine.support` adds `build_runtime_lock()`, `RuntimeLock`, `read_runtime_lock()`, `compare_runtime_locks()` and `LockDifference`. A `lock/v1` document records the engine, NumPy, pandas, PyArrow, Python, seed protocol, time zone, compatibility phase, Faker version, a provider registry digest, a digest of the shipped data files, the versions of the engine's other base dependencies and an optional `key_version` label. It holds no key, no key check value, no path and no host name. The reader refuses an unknown tag, a missing field and a wrong type, and ignores a field added under `lock/v1`. `compare_runtime_locks` names each field that differs.

`decoy_engine.keyprovider.is_key_version_label()` is the one check of the `key_version` label rule. The resume store records and the lock both use it. A bad label given to the lock raises `MaskSecretError` with the new reason `runtime/key_version_invalid`.
