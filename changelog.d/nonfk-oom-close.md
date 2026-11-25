### Added (end-to-end proof and docs for the non-FK memory guard, NONFK-OOM S5, 2026-11-25)

The route narrative in `docs/execution-backends.md` now covers large jobs with no foreign keys: the
three routes, the resident-fit verdict, what "before the read" means for each entry point, and that
`--max-memory` does not move the memory ceiling. The bench script
`scripts/bench-auto-chunk/bench_nonfk_fallthrough.py` now records a refused run and an end-to-end
`decoy run` under a memory cap. The end-to-end run writes only into a fresh subdirectory of
`--workdir`, only the registered capacity refusal counts as a refusal, and the lower bound binds
full-frame trials only (`--phase after` expects W-P on the chunked route).
No engine behavior changes in this slice.
