### Added (model hits in the pre-scan, SCAN-ML M3a, 2026-11-16)

`scan_sources` takes a keyword `pre_scan` (a `PreScanConfig`). With `classifier` or `ner` in its
`detectors`, the scan loads those models strictly before the first table and records one
`ModelHit` per column and detector in `TableScan.model_hits`. The classifier reads a 60-row
subsample per column and a `high` or `review` band is a hit. NER scores free-text columns only and a
hit carries a rate bucket (`<10%`, `10-50%`, `>=50%`). `ScanSet.detectors` lists each source that
ran with its model id and version, and `scan-set/v1` gains `detectors` and a per-field `model_hits`,
both additive: a record written earlier still validates and reads back with empty lists. The scan
logs `pre_scan.detectors` and one `pre_scan.models` line per table on `decoy_engine.detectors`,
counts only. `starter_config` ignores model hits until the suggestions land in a later slice.
`pre_scan=None`, the default, runs the regex detectors as before.
