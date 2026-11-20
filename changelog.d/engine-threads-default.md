### Changed (engine thread default, ENGINE-THREADS-DEFAULT, 2026-11-20)

`run_pipeline` uses the usable CPU cores for native kernels by default instead of one thread. Pass `native_threads=1` for the old behavior. Output is the same on every route. The run record gains `quality_metrics["execution"]["native_threads"]` and `["native_threads_source"]` (`explicit`, `auto` or `auto_fallback`).
