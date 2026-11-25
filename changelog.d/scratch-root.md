### Changed (one scratch root and temp budget, F25 G6-1, 2026-11-24)

One function, `fileaccess.scratch_root()`, now names the directory every engine scratch root goes under. The first non-empty variable of `TMPDIR`, `TEMP` and `TMP` chooses it. If that directory cannot take a new directory, the run stops with `runtime/scratch_root_unusable` instead of moving to another temp directory. The out-of-core disk preflight and the runtime temp-disk cap measure the directory the run spills under.
