### Changed (NER not-installed message and resume model identity, SCAN-ML-MD M-2a2, 2026-11-17)

A missing NER model is now refused with one message for every surface (`pre_scan`, `post_scan`, `text_redact`, `text_mask`). It names the surface, the refused model, that model's pinned wheel URL and the config key that selects another model. The text carries no config value other than the model name. `ner_status()` and `ner_rates()` resolve a missing `model` through the one resolver, and the `NER_MIN_RATE` alias is removed.

`build_fingerprint` now adds one engine-owned `decoy-ner:<surface>` component per NER surface the run uses, holding the resolved model and installed version. A run resumed under a different NER model is refused with `resume.fingerprint_changed`. A caller component whose name starts with `decoy-ner:` raises `ValueError`. A run with no NER surface has the same fingerprint as before. A resume record written earlier for a run with NER is refused once.
