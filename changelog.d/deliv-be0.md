Breaking: `PipelineConfig` and `compile_plan` refuse `delivery.mode: best_effort`, a value that was accepted and had no effect.

### Changed (best_effort delivery refused at validation, DELIV BE0-E, 2026-11-27)

`delivery: {mode: best_effort}` now fails validation with the new reason `config/delivery_best_effort_unreleased`, reported at the location `delivery`. No run implemented the mode, so a config that asked for it ran as `strict` without a word. `decoy_engine.config.refuse_unreleased_delivery` runs the same refusal on a raw mapping, and `compile_plan` calls it first for entries that never build a `PipelineConfig`. `strict` and an omitted block behave as before, and `DeliveryConfig` and the frozen config schema still list `best_effort`, so lifting the refusal later is additive.
