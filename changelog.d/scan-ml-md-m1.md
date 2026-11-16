Breaking: a `pre_scan` or `post_scan` config that names an NER model other than en_core_web_sm or en_core_web_md (for example en_core_web_lg) now refuses at load with `provider/ner_model_uncalibrated`; `text_redact` is unaffected.

### Added (per-model NER hit rates and the md wheel, SCAN-ML-MD M-1, 2026-11-16)

The NER hit threshold is now per model (`NER_MIN_RATES`): en_core_web_sm keeps 0.211 and en_core_web_md gets 0.122, measured by the same rule over the calibration corpus plus a committed clinical-vocabulary negative corpus (Synthea drug, vaccine, lab, procedure, condition and device terms, pinned by digest). `NerRate` carries its threshold. `NER_MODEL_WHEELS` pins the en_core_web_md 3.8.0 wheel, and the ner-gate CI job installs every pinned wheel. The default NER model is unchanged. `load_detectors` refuses an installed NER model that has no calibrated rate with `provider/ner_model_uncalibrated`, before any row is read.
