### Added (end-to-end proof and docs for the non-FK memory guard, NONFK-OOM S5, 2026-11-25)

The route narrative in `docs/execution-backends.md` now covers large jobs with no foreign keys: the
three routes, the resident-fit verdict, what "before the read" means for each entry point, and that
`--max-memory` does not move the memory ceiling. The measured before and after numbers, and an
end-to-end `decoy run` case under a memory cap, are in
`docs/records/2026-11-19-nonfk-oom-baseline.md`. The bench script
`scripts/bench-auto-chunk/bench_nonfk_fallthrough.py` records a refused run and an end-to-end run.
No engine behavior changes in this slice.
