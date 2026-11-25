Breaking: a job with a `validators:` block now takes the route the same job takes without it for the unified slice, the mixed route and the physical full-frame, mixed and generation drivers, so its output bytes are that route's bytes (see `tests/parity/SEMANTIC_DIFFERENCES.md`); the physical plan hash no longer includes the validator count.

### Changed (validators run on the resident route that was chosen, EXPECT-OFF-ROUTE S2, 2026-11-24)

`execute_route` opens one validation session beside the post-scan gate, before any source is read, so
a bad validator entry fails at the start of the run. It feeds the session every resident output that
no earlier step folded, finishes it before `settle`, and stores the report in
`quality_metrics["validation"]`. On the unified slice, full frame, the mixed route and the physical
drivers, a failing check raises `ValidatorFailedError` before the run returns. The out-of-core route
checks each batch as the sink receives it, after declared formatting, and a `TransactionalSink`
aborts on a failure. A standalone `ShadowCoordinator.run` of a generation or mixed plan also raises
when its configured validators reject the result. A bad validator entry or parameter is reported by
entry index and parameter name, never by value. A table has one folding observer: a second observer adds nothing.
Validators do not change what a plain callable sink receives. The unified slice judges the rendered
bytes after post-mask quarantine, as full frame does. A lazy source that a check pairs with its output
is read in batches.

The unified slice, the mixed route and the physical drivers no longer decline a job for having
validators. The streamed and bounded routes (auto-chunk streamed, sequential foreign-key,
out-of-core, multi-table split) still keep a validator-bearing job resident until the next slice.
`ShadowContext.from_key_provider` no longer takes `validators` and `ShadowContext` has no
`validators_requested`, because validators do not decide admission.

A validator parameter error or finding never carries the parameter text: a bad regex, a non-numeric
`max_identical_ratio`, `min_rows` or `tolerance` is reported by validator and parameter name through one
parser (`validators/_params.py`), and a failing `regex_match` finding no longer quotes its pattern.
A standalone shadow run with a validation session bound feeds that session instead of skipping it, and a
standalone full-frame run judges its result when the context carries `validation_config`.

Every table a run delivers is judged exactly once. Marking a table complete no longer counts as
judging it: `ValidationSession.close()` finishes the session, then raises `ValidatorFailedError` for a
finding on any table no caller judged, whichever step fed it. Full frame's quarantine pass records
its verdict, so a covered failure is not raised twice. The out-of-core collector records its own
verdict under an owner token. A step may leave a table to another caller only with an explicit owner
token (`ShadowContext.validation_owner`; the unified slice sets it), and `close()` refuses a table
that was deferred or marked complete but never fed, with the new reason code
`validator_table_not_observed`.
