Breaking: a config where two declared tables share one target destination now refuses (`config/target_shared_destination`); give each table its own target. `config.target_identity` is removed in favour of `config.duplicate_target_groups`.

### Changed (one destination per table, DUP-DEST-E1, 2026-11-14)

`PipelineConfig` validation refuses (`config/target_shared_destination`) two declared tables whose targets write to one destination, so the second write can no longer replace the first. File paths compare after normalization unless they contain `..`, S3 targets by endpoint, bucket and key, GCS targets by bucket and object. Targets whose key names no declared table are ignored. `decoy_engine.config.duplicate_target_groups` is the one grouping function.
