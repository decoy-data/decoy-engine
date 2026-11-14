### Added (starter_config builder, SCAN-MULTI S3-engine.2, 2026-11-14)

`profiling.starter_config(scan, *, baseline_path, targets, seed, relationships)` turns a `ScanSet` into one starter pipeline config (`StarterConfig`: `config`, REVIEW `notes`, `suggestions`, `relationship_template`). Every column gets an entry, and a column no detector flagged is redacted with a note. Declared relationships are copied unchanged and never inferred. Their key columns hash under one shared namespace, or under the reserved `decoy-set-namespace-<n>` placeholder when none is declared, which `PipelineConfig` refuses until the user sets a real one. Cloud sources write to a local `masked/` folder with a note.

`contracts.strategy_requirements` now holds the strategy requirement table (`StrategyRequirement`, `REQUIREMENTS_BY_STRATEGY`, `requirements_for`, `requirement_applies`); `plan.checks` re-exports the same names. `config.relationship_shape_error` is the shared shape check for a declared relationship (unknown table, key column count, missing key column). `starter_config` refuses two tables that would write one target path, and an empty explicit target.

`config.target_identity` is the one definition of "same destination" (normalized file path, S3 bucket and key, GCS bucket and object). `starter_config` compares it, so two equal cloud targets or `out/a.csv` and `out/./a.csv` are refused.
