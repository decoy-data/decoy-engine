### Added (a job with no foreign keys is refused before it can run out of memory, NONFK-OOM, 2026-11-22)

Under `auto`, a job with no foreign keys that stays on the full-frame route is now priced before
the route opens an output. If the input plus one pandas copy of it is larger than the memory the
host or cgroup allows, or a measured probe clears that ceiling by the calibration band, the run
stops with `runtime/nonfk_full_frame_capacity_exceeded`. This is a capacity code, so `decoy run`
exits 5. A job between 85% of the ceiling and the ceiling still runs as before. The verdict is
stored on the route decision (`RouteDecision.resident_fit`) using `route/nonfk_full_frame_fits`,
`route/nonfk_full_frame_probe_fits` and `route/nonfk_full_frame_unverified`. A lazy source is
priced from its Parquet footer; the CLI's own whole read of a source is not covered here.
`execution_mode="full_frame"` is never priced.
