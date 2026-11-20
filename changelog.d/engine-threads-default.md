### Changed (engine thread default, ENGINE-THREADS-DEFAULT, 2026-11-20)

`run_pipeline` uses the usable CPU cores for native kernels by default instead of one thread. Pass `native_threads=1` for the old behavior. Output is the same on every route. The run record gains `quality_metrics["execution"]["native_threads"]`, a mapping with `count` (the requested value; the kernels apply at most 4) and `source` (`explicit`, `auto` or `auto_fallback`). A memory-capped `run_pipeline_isolated` call that omits `native_threads` uses one thread.
