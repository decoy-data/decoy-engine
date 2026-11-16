### Changed (24e E0, 2026-11-16)

The table that maps each strategy to its distribution behavior moved from the private module `execution/_distribution_behavior.py` to `decoy_engine.contracts.distribution_behavior`, so the plan layer reads it without importing `execution`. The labels and `distribution_behavior_for` are unchanged, and no output or manifest byte moves. The type alias of the labels is private (`_DistributionBehavior`).
