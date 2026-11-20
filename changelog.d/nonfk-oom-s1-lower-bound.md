### Added (resident lower bound, NONFK-OOM S1, 2026-11-19)

`decoy_engine.execution.pipeline` exports `lower_bound_bytes`, `TableBytesSpec`, `resident_spec` and `lazy_spec`: a pure strict lower bound on the bytes a full-frame run holds resident (input tables plus one pandas copy). Nothing in the run path calls it yet; the NONFK-OOM baseline bench does.
