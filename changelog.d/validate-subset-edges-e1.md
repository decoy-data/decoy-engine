### Changed (subset edge directions are checked in the split, VALIDATE-SUBSET-EDGES, 2026-11-24)

`split_subset_config` now checks the `subset:` edge directions, so a bad edge is refused before any source is read, on every path that splits a config: `run_pipeline` (including `subset_request="skip"`), `validate_plan` and the CLI gate. The codes stay `subset_unknown_edge` and `subset_dangling_not_acknowledged`. A `SubsetRequest` override skips the block it replaces, so it is not refused for that block. The dangling refusal text names `allow dangling` (`.decoy`) and `allow_dangling: true` (YAML) before the Python `FanOutPolicy` spelling.

`decoy_engine.subset` adds `drop_subset_block(config)`, the run config with its `subset` block set to `None` (the input dict itself when it has no block).
