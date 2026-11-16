Breaking: a generate snapshot with a negative or non-finite weight or count is now refused at run, even when its total is positive

### Changed (one degenerate-snapshot rule for validate and run, QA-GATE G-eng, 2026-11-16)

A statistical snapshot with a negative or non-finite weight or count is now refused with `statistical_stats_degenerate` by the sampler, window admission and the compile check alike. Before, the sampler only refused a total of zero or less, so a snapshot with one negative weight and a positive total was sampled at run. The compile check that `decoy validate` runs now applies the same rule, so a snapshot with an empty label set or all-zero counts is refused before the run, with the code the run gives.

#### Offline declared-column request

`DeclarationRequest.for_validate(config)` reads the header or footer of local file sources only and never opens an `s3` or `gcs` source. Its `remote_sources` property names the sources it skipped so a caller can report them as not checked. `decoy run` keeps using `for_descriptors`, which still refuses a missing declared column before any row.
