### Changed (Detector lists no longer need regex, INIT-SCAN-SCAFFOLD E1, 2026-11-26)

A `pre_scan` or `post_scan` detector list without `regex` is accepted and completed instead of refused with `config.detectors_invalid`: `[ner]` parses as `[regex, ner]` and `[]` as `[regex]`. Repeats and unknown sources still raise, and `ner_model` without `ner` still raises. The run-start pre-scan check uses the same rule through `PreScanConfig`, so its verdict is unchanged.
