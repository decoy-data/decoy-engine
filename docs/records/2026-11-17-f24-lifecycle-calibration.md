Status: record

# F24 lifecycle estimate: accuracy calibration (84-E1)

Two runs. The first (head `b1213e83a`) found four cells below the measured peak and the plan
was amended (revision 5, section 4.2a: execute priced on each column's working spec, the larger of
its input and output cell, from the strategy handlers' own declarations). The second run, below,
is on the revision 5 build; head recorded in the PR.

Method: Linux test VM through `vm-run`, one child process per cell, peak RSS from `wait4`
`ru_maxrss` outside the child, fixtures built in a separate process. The worker reads each source
whole, runs `run_pipeline` on the resident tables and writes every target. It passes the CLI's
`auto` resource kwargs (`native_threads` and `out_of_core_threads` from `detect_usable_cpus`,
`out_of_core_budget_bytes` from `resolve_conservative_ooc_budget_bytes`, the engine helpers the
CLI uses) and the default native gate (the CLI passes `unified_slice_enabled` only to turn it
off). The CLI package is not importable from the engine repo, so the kwargs are rebuilt from the
engine helpers rather than from the CLI's `_resources` module. It does not pass the vault writer,
quarantine path or report flags.

Result: 14 of 14 cells pass.

| Cell | Rows | Predicted route | Realized route | Limiting phase | Predicted MB | Measured MB | Ratio | Result |
|---|---|---|---|---|---|---|---|---|
| AT-E1-17 | 1M | full_frame | full_frame | execute | 2190 | 722 | 3.03 | pass (lower) |
| AT-E1-17 | 3M | full_frame | full_frame | execute | 6541 | 1703 | 3.84 | pass (lower) |
| AT-E1-18 | 1M | sequential | out_of_core | execute | 1382 | 597 | 2.31 | pass (lower) |
| AT-E1-18 | 3M | sequential | out_of_core | execute | 3820 | 1216 | 3.14 | pass (lower) |
| AT-E1-19 | 1M | sequential | sequential | execute | 1149 | 621 | 1.85 | pass (lower) |
| AT-E1-19 | 3M | sequential | sequential | execute | 3047 | 1492 | 2.04 | pass (lower) |
| AT-E1-23 | 1M | full_frame | full_frame | execute | 1688 | 402 | 4.19 | pass (lower) |
| AT-E1-23 | 3M | full_frame | full_frame | execute | 4663 | 792 | 5.89 | pass (lower) |
| AT-E1-24 | 1M | full_frame | full_frame | execute | 1164 | 645 | 1.81 | pass (lower) |
| AT-E1-24 | 3M | full_frame | full_frame | execute | 3207 | 1614 | 1.99 | pass (lower) |
| AT-E1-25 | 1M | full_frame | full_frame | execute | 2052 | 1059 | 1.94 | pass (lower) |
| AT-E1-25 | 3M | full_frame | full_frame | execute | 6102 | 2761 | 2.21 | pass (lower) |
| AT-E1-27 | 1M | full_frame | full_frame | execute | 794 | 749 | 1.06 | pass (bounded 1.5) |
| AT-E1-27 | 3M | full_frame | full_frame | execute | 1983 | 1637 | 1.21 | pass (bounded 1.5) |

Revision 5 prediction check: AT-E1-19 predicted 1149 and 3047 MB and AT-E1-23 1688 and 4663 MB,
the figures section 4.2a computed ahead of the build. AT-E1-19 and AT-E1-23 write strings from
int64 columns, so they take the lower bound only. AT-E1-27 keeps the 1.5 bound and passes.
Realized and predicted routes differ for AT-E1-18 (sequential predicted, out_of_core realized,
FM-6); it takes the lower bound.

## First run (revision 4 model, head `b1213e83a`)

AT-E1-19 0.46 and 0.32, AT-E1-23 0.96 and 0.95 (predicted over measured); the other ten cells
passed. Cause: the basis priced every column at its input cell, but those cells are rewritten to
strings by `hash` and `redact`.
