### Changed (code_set memo, CODE-SET-NATIVE, 2026-11-24)

In mask mode the `code_set` handler masks each distinct value once per call and reuses the code for repeats, up to a memory cap of 65,536 entries or 8 MiB of key text. Past a cap, new values are masked one call at a time as before. Output, row errors and evidence do not change. Gen mode is unchanged.
