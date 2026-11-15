### Added (frozen-surface map and schema snapshots, REL-GATE RG-F1, 2026-11-15)

`docs/frozen-surfaces.md` lists each surface that freezes at 1.0.0 with the code that owns it and the test that pins it; a sentry fails when a contract 3.1 tag or a public name has no row. The JSON schemas of `PipelineConfig` and `RunResult` are committed under `tests/snapshots/frozen_schemas/` and checked by `scripts/release/frozen_schemas.py --check`, which prints a file name and a JSON pointer, never a value. The compatibility pre-flight now also covers `run_result/`, `reasons/` and the schema snapshots.
