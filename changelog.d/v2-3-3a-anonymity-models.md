### Added (privacy-model descriptors and frequency sets, V2-3.3 Part A, 2026-11-18)

V2 track, library-only, reached by import. `decoy_engine.quality.anonymity` gains the privacy
models as descriptors (`KAnonymity`, `DistinctLDiversity`, `EntropyLDiversity`,
`RecursiveCLDiversity`, `EqualTCloseness`, `OrderedTCloseness`), each stating which classes fail
it by the same rules as the `measure_*` functions, and `FrequencySet` (Incognito), the classes of
a table with their sizes and sensitive counts, rolled up to coarser generalizations without
regrouping rows. `type_family`, the one value-identity rule, moves to the private bottom-tier
module `decoy_engine._value_family`, so `quality.anonymity` and `anonymize` share one definition
without importing each other; `decoy_engine.anonymize.type_family` is unchanged. No measure's
report changes, and nothing in config, the planner or a run reaches these names.
