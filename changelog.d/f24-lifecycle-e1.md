### Added (full-lifecycle estimate for mask jobs, F24 84-E1, 2026-11-17)

`estimate_job` now returns three more fields on `JobEstimate`, all defaulted: `lifecycle_peak_bytes`, `limiting_phase` and `phase_bytes`. They give the largest of three phase peaks (ingest, execute, write) for a caller that reads every file source whole, holds inputs and outputs, and writes the last target, and name the phase that sets it. The ingest and write phases are new. The execute phase is the existing measured model, plus the input tables the caller holds that the measurement did not. The estimate stays advisory: it never raises, gates or changes a route, and its notes hold names, byte counts and exception type names only. No reason code is added.

Three values change on a mask job with string columns that used to be unpriceable (a CSV source is all strings): `priceable` goes from False to True, `peak_bytes` from None to a number, and `runtime` from None to a band. Each string width now comes from a sample of at most 10,000 rows of the source file. A column with no value in that sample, or a type with no size model, still leaves the job unpriceable and is named in the notes.

New note texts: `row counts estimated from file size` and the `lifecycle not priced: ...` family. A consumer that keeps a set of known note shapes (the platform's `_KNOWN_NOTE_SHAPES`) must add them at its next engine repin.

Generate-only and mixed jobs, and subset jobs, get no lifecycle fields yet.
