### Added (synthetic probe and the `probe` lock field, 78-E2, 2026-11-17)

`decoy_engine.support` adds `run_probe()`, `probe_status()` and `ProbeError`. The probe runs fixed public inputs through the keyed hash core, FF1 and the seeded Faker pool, and returns a SHA-256 digest. `probe_status(digest)` is `ok` only when the digest equals the golden for the current seed protocol (`PROBE_GOLDEN`), and `mismatch` otherwise, including a protocol with no golden row. The probe covers the Python reference path; the native companion has its own known-answer vectors. It reads no key, file or environment variable. It refuses to run while a custom provider overrides `person_first_name`. A failure raises `ProbeError` with the new reason `runtime/probe_failed` and fixed text.

`lock/v1` gains an optional `probe` field. `build_runtime_lock()` always sets it. A lock written without it still reads (as `None`) and rewrites to the same bytes; a `null` `probe` is refused.

`decoy_engine.providers_v2.custom_provider_names()` is the public reader of the V2 custom-provider table (the former private `_v2_custom_provider_names`, renamed).

The probe golden changes only in a PR that bumps the seed protocol or repins Faker, and that PR's fragment names the change. The CI `import-smoke` job now runs the probe on Python 3.11.9 and 3.12.7.
