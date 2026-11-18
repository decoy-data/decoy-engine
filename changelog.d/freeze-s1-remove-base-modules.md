### Removed (unused strategy base modules, FREEZE-S1, 2026-11-18)

`decoy_engine.internal.base` (`MaskingStrategy`, the config validator and IO handler base classes) and `decoy_engine.transforms.base` (`BaseMaskingStrategy`) are removed. Nothing in the engine or the CLI used them. `decoy_engine.transforms.__all__` is now empty. `FormulaStrategy` keeps its name, module path and output; it is now a plain class that logs through its module logger.
