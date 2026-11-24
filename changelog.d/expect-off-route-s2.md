Breaking: a job with a `validators:` block now takes the route the same job takes without it for the unified slice, the mixed route and the physical full-frame, mixed and generation drivers, so its output bytes are that route's bytes (see `tests/parity/SEMANTIC_DIFFERENCES.md`); the physical plan hash no longer includes the validator count; a plain callable `sink` now receives each resident output table once, after validation and the post-scan check, when the run has validators.

### Changed (validators run on the resident route that was chosen, EXPECT-OFF-ROUTE S2, 2026-11-24)

`execute_route` opens one validation session beside the post-scan gate, before any source is read, so
a bad validator entry fails at the start of the run. It feeds the session every resident output that
no earlier step folded, finishes it before `settle`, and stores the report in
`quality_metrics["validation"]`. A failing check raises `ValidatorFailedError` before any table
reaches a callable sink. A table has one folding observer: a second observer adds nothing.

The unified slice, the mixed route and the physical drivers no longer decline a job for having
validators. The streamed and bounded routes (auto-chunk streamed, sequential foreign-key,
out-of-core, multi-table split) still keep a validator-bearing job resident until the next slice.
`ShadowContext.from_key_provider` no longer takes `validators` and `ShadowContext` has no
`validators_requested`, because validators do not decide admission.
